#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox 聚合源生成脚本（跨平台：Windows / Linux / macOS / GitHub Actions）
============================================================
功能：
  1. 从 sources.txt 读取候选源地址
  2. 逐个测试可用性并抓取内容
  3. 合并点播源(sites)与直播源(lives)，自动去重
  4. 尽力把源引用的播放插件 jar 下载到本地 jars/ 目录并重写路径
  5. 生成 tvbox.json —— 这就是电视配置地址最终指向的文件

用法：
  python fetch_sources.py

部署场景：
  - 本地：跑完用 python -m http.server 8000 提供文件，电视配置 http://<本机IP>:8000/tvbox.json
  - Cloudflare Pages：GitHub Actions 定时跑本脚本，产物自动部署，电视配置 https://tvbox.你的域名/tvbox.json
"""
import json
import os
import re
import socket
import sys
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(BASE_DIR, "sources.txt")
OUT_FILE = os.path.join(BASE_DIR, "tvbox.json")
JAR_DIR = os.path.join(BASE_DIR, "jars")

TIMEOUT = 20
UA = "Mozilla/5.0 (Linux; Android 7.0; TV) AppleWebKit/537.36"

# 内置默认源（sources.txt 不存在或为空时使用；也方便直接改这里）
DEFAULT_SOURCES = [
    "https://raw.liucn.cc/box/m.json",
    "http://home.jundie.top:81/top98.json",
    "https://cdn.jsdelivr.net/gh/liu673cn/box@main/m.json",
    "https://ghproxy.net/https://raw.githubusercontent.com/liu673cn/box/main/m.json",
]


def load_sources():
    """读取源地址清单；文件不存在则用内置默认"""
    if os.path.exists(SOURCES_FILE):
        with open(SOURCES_FILE, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f
                     if ln.strip() and not ln.strip().startswith("#")]
        if lines:
            return lines
    return DEFAULT_SOURCES


def http_get(url, timeout=TIMEOUT, binary=False, retries=2):
    """抓取 URL 内容；瞬时断连自动重试，失败抛异常由调用方处理"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            return data if binary else data.decode("utf-8", "ignore")
        except Exception as e:
            last_err = e
            if attempt < retries:
                import time
                time.sleep(2)
    raise last_err


def try_parse_json(text):
    """解析 JSON；自动删除所有整行的 // 注释（不少源配置带注释，JSON 标准不允许）"""
    lines = []
    for ln in text.splitlines():
        if ln.lstrip().startswith("//"):
            continue
        lines.append(ln)
    text = "\n".join(lines)
    try:
        return json.loads(text)
    except Exception:
        return None


def normalize_jar_url(base_url, ref):
    """把源里的相对 jar 路径解析为绝对 URL"""
    if ref.startswith("http://") or ref.startswith("https://"):
        return ref
    m = re.match(r"^(https?://[^/]+)(/.*)?$", base_url)
    if not m:
        return None
    host, path = m.group(1), m.group(2) or "/"
    if ref.startswith("/"):
        return host + ref
    dir_path = os.path.dirname(path)
    if dir_path.endswith("/"):
        dir_path = dir_path[:-1]
    return host + dir_path + "/" + ref.lstrip("./")


def download_jar_to_local(url, force_name=None):
    """下载 jar 到本地 jars/，返回本地相对路径 ./jars/xxx.jar；失败返回 None"""
    try:
        os.makedirs(JAR_DIR, exist_ok=True)
        name = force_name
        if not name:
            name = os.path.basename(urllib.parse.urlparse(url).path)
        if not name or not name.endswith(".jar"):
            name = (name or "spider") + ".jar"
        name = os.path.basename(name)  # 防路径穿越
        dest = os.path.join(JAR_DIR, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return "./jars/" + name
        data = http_get(url, timeout=30, binary=True)
        if not data:
            return None
        with open(dest, "wb") as f:
            f.write(data)
        print(f"    [jar] 已下载 {name} ({len(data)} bytes)")
        return "./jars/" + name
    except Exception as e:
        print(f"    [jar] 下载失败 {url} -> {e}")
        return None


def rewrite_spider(base_url, spider_str, local_map):
    """处理顶层 spider 字段，如 './fty.jar;md5;xxx' → './jars/fty.jar;md5;xxx'"""
    m = re.search(r'([^\s"\'>,;]+\.jar)', spider_str)
    if not m:
        return spider_str
    ref = m.group(1)
    if ref in local_map:
        return spider_str.replace(ref, local_map[ref], 1)
    abs_url = normalize_jar_url(base_url, ref)
    local = download_jar_to_local(abs_url) if abs_url else None
    if local:
        local_map[ref] = local
        return spider_str.replace(ref, local, 1)
    return spider_str


def localize_jars(base_url, cfg, local_map):
    """把单个源配置里的 jar 引用本地化（顶层 spider + 各 site 的 jar 字段）"""
    if isinstance(cfg.get("spider"), str) and ".jar" in cfg["spider"]:
        cfg["spider"] = rewrite_spider(base_url, cfg["spider"], local_map)
    for site in cfg.get("sites") or []:
        if isinstance(site, dict) and isinstance(site.get("jar"), str):
            abs_url = normalize_jar_url(base_url, site["jar"])
            local = download_jar_to_local(abs_url) if abs_url else None
            if local:
                site["jar"] = local


def merge_configs(configs):
    """合并多个源配置：sites 按 key 去重，lives 按 name/group 去重"""
    sites, lives = [], []
    seen_sites, seen_lives = set(), set()
    spider = None
    for cfg in configs:
        for s in cfg.get("sites") or []:
            if not isinstance(s, dict):
                continue
            key = s.get("key")
            if key in seen_sites:
                continue
            seen_sites.add(key)
            sites.append(s)
        for lv in cfg.get("lives") or []:
            if not isinstance(lv, dict):
                continue
            nm = lv.get("name") or lv.get("group")
            if nm and nm in seen_lives:
                continue
            if nm:
                seen_lives.add(nm)
            lives.append(lv)
        if spider is None and isinstance(cfg.get("spider"), str):
            spider = cfg["spider"]
    out = {}
    if spider:
        out["spider"] = spider
    if sites:
        out["sites"] = sites
    if lives:
        out["lives"] = lives
    if not out:
        raise RuntimeError("所有源均不可用或为空")
    return out


def local_ip():
    """获取本机局域网 IP（本地部署时提示用）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "未知"


def main():
    print("=" * 60)
    print("TVBox 聚合源生成脚本")
    print("=" * 60)
    sources = load_sources()
    print(f"候选源共 {len(sources)} 个\n")

    configs = []
    local_map = {}
    ok = 0
    for url in sources:
        print(f"抓取: {url}")
        try:
            text = http_get(url)
            cfg = try_parse_json(text)
            if not cfg:
                print("  x 内容不是有效 JSON，跳过")
                continue
            base = url
            localize_jars(base, cfg, local_map)
            configs.append(cfg)
            ok += 1
            print(f"  OK  点播 {len(cfg.get('sites') or [])} 个 / 直播 {len(cfg.get('lives') or [])} 个")
        except Exception as e:
            print(f"  x 抓取失败: {e}")

    if not configs:
        print("\n错误：没有任何源可用，请检查 sources.txt 或网络")
        sys.exit(1)

    merged = merge_configs(configs)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)

    print("\n" + "=" * 60)
    print(f"完成！合并自 {ok} 个可用源")
    print(f"  点播源 sites: {len(merged.get('sites', []))} 个")
    print(f"  直播源 lives: {len(merged.get('lives', []))} 个")
    print(f"  输出文件: {OUT_FILE} ({os.path.getsize(OUT_FILE)} bytes)")
    ip = local_ip()
    print(f"\n本地部署时电视配置地址: http://{ip}:8000/tvbox.json")
    print("（Cloudflare Pages 部署时用公网地址）")
    print("=" * 60)


if __name__ == "__main__":
    main()

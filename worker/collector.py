import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "TVBox-Config-Collector"
}

TOKEN = os.environ.get("GH_TOKEN", "")
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

OUTPUT = "接口列表.txt"
CHECK_OUTPUT = "接口检测结果.txt"

# 搜索公开的影视仓、TVBox 配置项目
SEARCH_TERMS = [
    "影视仓",
    "TVBox",
    "TVBox 配置",
    "tvbox config",
    "catvod",
    "影视接口"
]

# 识别影视仓配置中常见的字段
CONFIG_KEYS = {
    "sites", "lives", "parses", "spider",
    "rules", "doh", "wallpaper", "ijk",
    "drives", "api", "urls"
}

TIMEOUT = 12
MAX_REPOS_PER_QUERY = 20
MAX_JSON_FILES_PER_REPO = 30


def request(url, timeout=TIMEOUT):
    """获取网页内容。"""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except Exception as exc:
        print(f"[请求失败] {url}：{exc}")
        return None


def load_json(data):
    """解析 JSON。"""
    if not data:
        return None

    try:
        return json.loads(data.decode("utf-8-sig"))
    except Exception:
        return None


def is_tvbox_config(data):
    """判断 JSON 是否具有影视仓配置特征。"""
    if not isinstance(data, dict):
        return False

    keys = {str(key).lower() for key in data.keys()}

    # 至少包含一个常见配置字段
    if not keys.intersection(CONFIG_KEYS):
        return False

    # 排除明显不是影视仓配置的普通 JSON
    for key in ("sites", "lives", "parses", "spider", "rules"):
        value = data.get(key)

        if isinstance(value, (list, dict)) and value:
            return True

    return False


def github_search_repositories(keyword):
    """通过 GitHub 仓库搜索 API 查找公开项目。"""
    query = urllib.parse.urlencode({
        "q": keyword + " in:name,description,readme",
        "sort": "updated",
        "order": "desc",
        "per_page": MAX_REPOS_PER_QUERY
    })

    url = f"{API}/search/repositories?{query}"
    data = load_json(request(url))

    if not isinstance(data, dict):
        return []

    return data.get("items", [])


def get_repo_json_files(repo):
    """获取仓库默认分支中的 JSON 文件。"""
    owner = repo.get("owner", {}).get("login")
    name = repo.get("name")
    branch = repo.get("default_branch")

    if not owner or not name or not branch:
        return []

    encoded_branch = urllib.parse.quote(branch, safe="")
    url = (
        f"{API}/repos/{owner}/{name}"
        f"/git/trees/{encoded_branch}?recursive=1"
    )

    data = load_json(request(url))

    if not isinstance(data, dict):
        return []

    if data.get("truncated"):
        print(f"[提示] 仓库文件树被截断：{owner}/{name}")

    files = []

    for item in data.get("tree", []):
        if item.get("type") != "blob":
            continue

        path = item.get("path", "")
        lower = path.lower()

        if not lower.endswith(".json"):
            continue

        # 排除依赖、缓存和无关目录
        if any(part in lower for part in (
            "node_modules/",
            "vendor/",
            ".git/",
            "package-lock.json",
            "composer.json"
        )):
            continue

        files.append(path)

        if len(files) >= MAX_JSON_FILES_PER_REPO:
            break

    return files


def raw_url(repo, path):
    """生成 GitHub 原始文件地址。"""
    owner = repo["owner"]["login"]
    name = repo["name"]
    branch = urllib.parse.quote(repo["default_branch"], safe="")

    encoded_path = "/".join(
        urllib.parse.quote(part, safe="")
        for part in path.split("/")
    )

    return (
        f"https://raw.githubusercontent.com/"
        f"{owner}/{name}/{branch}/{encoded_path}"
    )


def collect_candidates():
    """搜索公开仓库并筛选配置文件。"""
    candidates = set()
    seen_repos = set()

    for keyword in SEARCH_TERMS:
        print(f"\n[搜索] {keyword}")

        repos = github_search_repositories(keyword)

        for repo in repos:
            full_name = repo.get("full_name", "")

            if not full_name or full_name in seen_repos:
                continue

            seen_repos.add(full_name)
            print(f"[仓库] {full_name}")

            files = get_repo_json_files(repo)

            for path in files:
                url = raw_url(repo, path)

                # 只接受实际可访问且符合配置结构的 JSON
                content = request(url)
                obj = load_json(content)

                if is_tvbox_config(obj):
                    candidates.add(url)
                    print(f"[发现配置] {url}")

                # 避免过快请求 GitHub
                time.sleep(0.15)

    return candidates


def check_config(url):
    """检查配置地址是否可访问且包含有效配置结构。"""
    content = request(url)
    obj = load_json(content)

    return is_tvbox_config(obj)


def read_old_urls(filename):
    """读取以前保存的地址，供下次运行继续检查。"""
    if not os.path.exists(filename):
        return set()

    with open(filename, "r", encoding="utf-8") as file:
        return {
            line.strip()
            for line in file
            if line.strip().startswith(("https://", "http://"))
        }


def write_lines(filename, urls):
    with open(filename, "w", encoding="utf-8") as file:
        for url in sorted(urls):
            file.write(url + "\n")


def main():
    print("=" * 50)
    print("影视仓配置接口自动采集器")
    print("运行时间：", datetime.now(timezone.utc).isoformat())
    print("=" * 50)

    # 搜索新配置
    new_urls = collect_candidates()

    # 合并历史地址，避免每次运行丢失以前的结果
    old_urls = read_old_urls(OUTPUT)
    all_urls = old_urls | new_urls

    print(f"\n新发现：{len(new_urls)} 个")
    print(f"历史地址：{len(old_urls)} 个")
    print(f"待检测总数：{len(all_urls)} 个")

    # 检查全部地址
    valid_urls = set()

    for index, url in enumerate(sorted(all_urls), start=1):
        print(f"[检测 {index}/{len(all_urls)}] {url}")

        if check_config(url):
            valid_urls.add(url)
            print("[有效配置]")
        else:
            print("[无法验证或配置格式不符]")

        time.sleep(0.2)

    # 接口列表保留所有已发现地址
    write_lines(OUTPUT, all_urls)

    # 检测结果只保存可访问且符合配置结构的地址
    write_lines(CHECK_OUTPUT, valid_urls)

    print("\n采集完成")
    print(f"累计地址：{len(all_urls)} 个")
    print(f"有效配置：{len(valid_urls)} 个")
    print(f"已生成：{OUTPUT}")
    print(f"已生成：{CHECK_OUTPUT}")


if __name__ == "__main__":
    main()

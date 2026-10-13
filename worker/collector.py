import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ==================== 基本配置 ====================

API = "https://api.github.com"
TOKEN = os.environ.get("GH_TOKEN", "")

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "TVBox-Config-Collector"
}

if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

# 获取仓库根目录
ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

# 结果文件保存到仓库根目录
OUTPUT = os.path.join(ROOT_DIR, "接口列表.txt")
CHECK_OUTPUT = os.path.join(ROOT_DIR, "接口检测结果.txt")

TIMEOUT = 15
MAX_REPOS_PER_QUERY = 30
MAX_JSON_FILES_PER_REPO = 40

SEARCH_TERMS = [
    "影视仓",
    "TVBox",
    "TVBox配置",
    "TVBox接口",
    "tvbox config",
    "catvod",
    "影视接口",
    "tvbox.json",
    "drpy",
]

CONFIG_KEYS = {
    "sites",
    "lives",
    "parses",
    "spider",
    "rules",
    "doh",
    "wallpaper",
    "ijk",
    "drives",
    "api",
    "urls",
}


# ==================== 网络请求 ====================

def request(url, timeout=TIMEOUT):
    try:
        req = urllib.request.Request(url, headers=HEADERS)

        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()

    except Exception as exc:
        print(f"[请求失败] {url}：{exc}")
        return None


def load_json(content):
    if not content:
        return None

    try:
        return json.loads(content.decode("utf-8-sig"))
    except Exception:
        return None


# ==================== 配置识别 ====================

def is_tvbox_config(data):
    if not isinstance(data, dict):
        return False

    keys = {str(key).lower() for key in data.keys()}

    if not keys.intersection(CONFIG_KEYS):
        return False

    for key in (
        "sites",
        "lives",
        "parses",
        "spider",
        "rules",
    ):
        value = data.get(key)

        if isinstance(value, (list, dict)) and value:
            return True

    return False


# ==================== GitHub 搜索 ====================

def github_search_repositories(keyword):
    query = urllib.parse.urlencode({
        "q": keyword + " in:name,description,readme",
        "sort": "updated",
        "order": "desc",
        "per_page": MAX_REPOS_PER_QUERY,
    })

    url = f"{API}/search/repositories?{query}"

    data = load_json(request(url))

    if not isinstance(data, dict):
        return []

    if "message" in data:
        print("[GitHub API]", data["message"])
        return []

    return data.get("items", [])


def get_repo_json_files(repo):
    owner = repo.get("owner", {}).get("login")
    name = repo.get("name")
    branch = repo.get("default_branch")

    if not owner or not name or not branch:
        return []

    branch_encoded = urllib.parse.quote(branch, safe="")

    url = (
        f"{API}/repos/{owner}/{name}"
        f"/git/trees/{branch_encoded}?recursive=1"
    )

    data = load_json(request(url))

    if not isinstance(data, dict):
        return []

    if data.get("truncated"):
        print(f"[提示] 文件树不完整：{owner}/{name}")

    files = []

    for item in data.get("tree", []):
        if item.get("type") != "blob":
            continue

        path = item.get("path", "")
        lower = path.lower()

        if not lower.endswith(".json"):
            continue

        excluded = (
            "node_modules/",
            "vendor/",
            ".git/",
            "__pycache__/",
        )

        if any(part in lower for part in excluded):
            continue

        files.append(path)

        if len(files) >= MAX_JSON_FILES_PER_REPO:
            break

    return files


def make_raw_url(repo, path):
    owner = repo["owner"]["login"]
    name = repo["name"]

    branch = urllib.parse.quote(
        repo["default_branch"],
        safe=""
    )

    encoded_path = "/".join(
        urllib.parse.quote(part, safe="")
        for part in path.split("/")
    )

    return (
        "https://raw.githubusercontent.com/"
        f"{owner}/{name}/{branch}/{encoded_path}"
    )


# ==================== 搜索配置 ====================

def collect_candidates():
    candidates = set()
    seen_repos = set()

    for keyword in SEARCH_TERMS:
        print(f"\n[搜索关键词] {keyword}")

        repos = github_search_repositories(keyword)

        print(f"[搜索结果] {len(repos)} 个仓库")

        for repo in repos:
            full_name = repo.get("full_name", "")

            if not full_name or full_name in seen_repos:
                continue

            seen_repos.add(full_name)

            print(f"\n[仓库] {full_name}")

            for path in get_repo_json_files(repo):
                url = make_raw_url(repo, path)

                content = request(url)
                data = load_json(content)

                if is_tvbox_config(data):
                    candidates.add(url)
                    print(f"[发现配置] {url}")

                time.sleep(0.2)

    return candidates


# ==================== 历史记录 ====================

def read_old_urls(filename):
    if not os.path.exists(filename):
        return set()

    urls = set()

    with open(filename, "r", encoding="utf-8") as file:
        for line in file:
            url = line.strip()

            if url.startswith(("https://", "http://")):
                urls.add(url)

    return urls


def write_lines(filename, urls):
    with open(filename, "w", encoding="utf-8") as file:
        for url in sorted(urls):
            file.write(url + "\n")


# ==================== 接口检测 ====================

def check_config(url):
    content = request(url)
    data = load_json(content)

    return is_tvbox_config(data)


def check_all(urls):
    valid_urls = set()
    total = len(urls)

    for index, url in enumerate(sorted(urls), start=1):
        print(f"\n[检测 {index}/{total}] {url}")

        if check_config(url):
            valid_urls.add(url)
            print("[结果] 可访问，JSON 配置结构有效")
        else:
            print("[结果] 无法访问或配置结构不符合要求")

        time.sleep(0.2)

    return valid_urls


# ==================== 主程序 ====================

def main():
    print("=" * 50)
    print("影视仓配置接口自动采集器")
    print("运行时间：", datetime.now(timezone.utc).isoformat())
    print("仓库根目录：", ROOT_DIR)
    print("=" * 50)

    # 读取历史记录
    old_urls = read_old_urls(OUTPUT)

    print(f"[历史记录] {len(old_urls)} 个地址")

    # 搜索公开仓库
    new_urls = collect_candidates()

    # 合并历史地址
    all_urls = old_urls | new_urls

    print("\n" + "=" * 50)
    print(f"本次发现：{len(new_urls)} 个")
    print(f"累计地址：{len(all_urls)} 个")
    print("=" * 50)

    # 检测所有历史及新发现地址
    valid_urls = check_all(all_urls)

    # 保存全部发现的地址
    write_lines(OUTPUT, all_urls)

    # 保存检测通过的地址
    write_lines(CHECK_OUTPUT, valid_urls)

    print("\n========== 运行完成 ==========")
    print(f"接口列表：{OUTPUT}")
    print(f"检测结果：{CHECK_OUTPUT}")
    print(f"累计地址：{len(all_urls)}")
    print(f"检测通过：{len(valid_urls)}")


if __name__ == "__main__":
    main()

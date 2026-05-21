#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
火币（HTX）批量自动化脚本 - 增强反检测版 V3
修复内容：
1. 区分注册接口和业务接口的User-Agent
2. 修正注册请求头（添加缺失头部、移除冗余头部）
3. 修正注册请求体参数
4. 增加随机延迟模拟人类行为
5. 完善Cookie管理（自动设置和携带Cookie）
6. 添加预热请求序列（模拟APP启动）
7. 添加背景请求（配置获取等）
8. TLS指纹伪装（使用curl_cffi）
9. 【修复】注册后登录时使用正确的请求头（原生APP风格而非WebView风格）
10. 【修复】get_ticket使用正确的API域名（l10n-pro.88maru.com）

增强反检测功能：
11. 【新增】添加abtest请求模拟真实APP行为
12. 【新增】请求间隔随机化（模拟HAR中的真实时间间隔）
13. 【新增】设备指纹一致性检查
14. 【新增】请求头顺序随机化
15. 【新增】更多设备型号池
16. 【新增】Chrome版本随机化
17. 【新增】请求时间戳抖动
18. 【新增】Session持久化优化
"""

from device_config import DeviceManager, ProxyManager
from Crypto.Util.Padding import pad
from Crypto.PublicKey import RSA
from Crypto.Cipher import AES, PKCS1_v1_5
import threading
import time
import json
import os
import re
import argparse
import sys
import io
import random
import hashlib
import binascii
import base64
import signal
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote
from collections import OrderedDict

# TLS指纹伪装 - 优先使用 tls_client，其次 curl_cffi，最后 requests
USE_TLS_CLIENT = False
USE_CURL_CFFI = False

try:
    import tls_client
    USE_TLS_CLIENT = True
    print("[*] 使用 tls_client 进行TLS指纹伪装")
except ImportError:
    try:
        from curl_cffi import requests as curl_requests
        USE_CURL_CFFI = True
        print("[*] 使用 curl_cffi 进行TLS指纹伪装")
    except ImportError:
        import requests as curl_requests
        USE_CURL_CFFI = False
        print("[!] TLS指纹库未安装，使用标准 requests（TLS指纹可能被识别）")


# 强制设置标准输出为 UTF-8 编码
if sys.stdout.encoding != 'utf-8' or not getattr(sys.stdout, 'line_buffering', False):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding='utf-8', line_buffering=True)

# ==================== 配置区 ====================
CAPMONSTER_KEY = "001185ed5d795d9feb2325c39829cf27"
INVITER_ID = 7890747
INVITE_CODE = ""  # 根据HAR，invite_code应为空字符串
RSA_PUBLIC_KEY = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCulDIsWM5Fgv0VNAQZbjhRdnSvc0+ICzezd5Q/2hL+oKCR2z8+Lm3O/ZCRIXTyFnDt3m2yvSueZyt8hCuIV+JKBM+5KJkIH2MlOEOsMTRaGPzhWdkLUb2j4DbcSmPcyXMP9TwVTgoGd0ISbxf1hZngsk0poy/1rCw+u4iLdxvt1QIDAQAB"
GET_CODE_API = "http://192.144.154.164/api/getcode.php"
ACTIVITY_ID = "177302900760253"  # 大转盘抽奖活动ID，根据需要修改

# API域名配置（根据HAR分析）
API_DOMAIN = "www.htx.com.hr"
API_DOMAIN_L10N = "l10n-pro.88maru.com"

# --- 批量配置 ---
MAX_WORKERS = 1  # 并发线程数
INPUT_FILE = "E:\\易语言源码\\trae\\ceshi2\\ccc\\emails.txt"
SUCCESS_FILE_SIMPLE = "success_accounts2.txt"
SUCCESS_FILE = "success_accounts.txt"
FAILURE_FILE = "failure_accounts.txt"
PROXY_API_URL = "https://api.jikip.com/ip-get?num=1&minute=1&format=txt&area=all&protocol=1&mode=1&key=13iodoar5glbqd"
MAX_RETRY_PER_ACCOUNT = 3

# --- 注册数量控制 ---
ENABLE_LIMIT = True
MAX_REGISTER_COUNT = 1
START_INDEX = 0

# --- 全局变量 ---
processed_emails = set()
file_lock = threading.Lock()
success_count = 0
success_lock = threading.Lock()
stop_event = None

# 空投抽奖失败计数器
airdrop_fail_count = 0
max_airdrop_failures = 50

# 空投抽奖成功的账号
airdrop_success_accounts = []
airdrop_success_lock = threading.Lock()

# ==================== 增强版设备池 ====================
ENHANCED_DEVICE_POOL = [
    # 小米系列
    {"brand": "Xiaomi", "model": "MI 13", "sys_ver": "13",
        "ua_model": "2211133C", "build": "TKQ1.220905.001"},
    {"brand": "Xiaomi", "model": "MI 14", "sys_ver": "14",
        "ua_model": "23127PN0CC", "build": "UKQ1.231003.002"},
    {"brand": "Xiaomi", "model": "Redmi K60", "sys_ver": "13",
        "ua_model": "23013RK75C", "build": "TKQ1.220905.001"},
    {"brand": "Xiaomi", "model": "Redmi K70", "sys_ver": "14",
        "ua_model": "23113RKC6C", "build": "UKQ1.231003.002"},
    {"brand": "Xiaomi", "model": "Redmi Note 12", "sys_ver": "13",
        "ua_model": "23021RAA2Y", "build": "TKQ1.220905.001"},
    # 三星系列
    {"brand": "Samsung", "model": "Galaxy S23", "sys_ver": "13",
        "ua_model": "SM-S9110", "build": "TP1A.220624.014"},
    {"brand": "Samsung", "model": "Galaxy S24", "sys_ver": "14",
        "ua_model": "SM-S9210", "build": "UP1A.231005.007"},
    {"brand": "Samsung", "model": "Galaxy A54", "sys_ver": "13",
        "ua_model": "SM-A5460", "build": "TP1A.220624.014"},
    {"brand": "Samsung", "model": "Galaxy Z Fold5", "sys_ver": "13",
        "ua_model": "SM-F9460", "build": "TP1A.220624.014"},
    # OPPO系列
    {"brand": "OPPO", "model": "Find X6", "sys_ver": "13",
        "ua_model": "PGFM10", "build": "TP1A.220905.001"},
    {"brand": "OPPO", "model": "Find X7", "sys_ver": "14",
        "ua_model": "PHZ110", "build": "UP1A.231005.007"},
    {"brand": "OPPO", "model": "Reno 10", "sys_ver": "13",
        "ua_model": "PHQ110", "build": "TP1A.220905.001"},
    # vivo系列
    {"brand": "vivo", "model": "X90", "sys_ver": "13",
        "ua_model": "V2241A", "build": "TP1A.220624.014"},
    {"brand": "vivo", "model": "X100", "sys_ver": "14",
        "ua_model": "V2310A", "build": "UP1A.231005.007"},
    {"brand": "vivo", "model": "iQOO 12", "sys_ver": "14",
        "ua_model": "V2307A", "build": "UP1A.231005.007"},
    # 华为系列（不使用GMS）
    {"brand": "HUAWEI", "model": "P60", "sys_ver": "12",
        "ua_model": "LNA-AL00", "build": "HUAWEILNA-AL00"},
    {"brand": "HUAWEI", "model": "Mate 60", "sys_ver": "12",
        "ua_model": "ALN-AL00", "build": "HUAWEIALN-AL00"},
    # 一加系列
    {"brand": "OnePlus", "model": "12", "sys_ver": "14",
        "ua_model": "PJD110", "build": "UP1A.231005.007"},
    {"brand": "OnePlus", "model": "11", "sys_ver": "13",
        "ua_model": "PHB110", "build": "TP1A.220905.001"},
    # 荣耀系列
    {"brand": "HONOR", "model": "Magic6", "sys_ver": "14",
        "ua_model": "BVL-AN00", "build": "HONORBVL-AN00"},
    {"brand": "HONOR", "model": "90", "sys_ver": "13",
        "ua_model": "REA-AN00", "build": "HONORREA-AN00"},
]

# Chrome版本池
CHROME_VERSIONS = [
    "116.0.5845.163",
    "117.0.5938.140",
    "118.0.5993.111",
    "119.0.6045.163",
    "120.0.6099.144",
    "121.0.6167.101",
    "122.0.6261.64",
    "123.0.6312.40",
]

# ==================== 随机延迟函数（增强版） ====================


def random_delay(min_sec=1.5, max_sec=4.0, description=""):
    """模拟人类操作的随机延迟（带正态分布抖动）"""
    # 使用正态分布使延迟更自然
    mean = (min_sec + max_sec) / 2
    std = (max_sec - min_sec) / 4
    delay = max(min_sec, min(max_sec, random.gauss(mean, std)))
    # 添加微小抖动
    delay += random.uniform(-0.1, 0.1)
    delay = max(0.1, delay)
    if description:
        print(f"[*] {description}，等待 {delay:.1f} 秒...")
    time.sleep(delay)


def short_delay():
    """短延迟（0.2-0.8秒）- 模拟快速操作"""
    random_delay(0.2, 0.8)


def medium_delay():
    """中等延迟（0.8-2.0秒）- 模拟正常操作"""
    random_delay(0.8, 2.0)


def long_delay():
    """长延迟（1.5-4.0秒）- 模拟思考/等待"""
    random_delay(1.5, 4.0)


def micro_delay():
    """微延迟（0.05-0.2秒）- 用于背景请求"""
    random_delay(0.05, 0.2)


def human_typing_delay():
    """模拟人类输入延迟（优化后：2-5秒）"""
    random_delay(2.0, 5.0)


def abtest_interval():
    """abtest请求间隔（优化后：0.5-1.5秒）"""
    random_delay(0.5, 1.5)


# ==================== 动态参数生成（增强版） ====================

def generate_trace_id():
    """生成x-b3-traceid（32位十六进制）"""
    return binascii.b2a_hex(random.randbytes(16)).decode()


def generate_ctx_id():
    """生成hb-ctx-id"""
    return str(random.randint(100000000, 999999999))


def generate_vulcan_uuid():
    """生成HB-VULCAN-UUID Cookie"""
    return str(uuid.uuid4())


def generate_urid():
    """生成URID Cookie"""
    return hashlib.sha256(str(time.time()).encode() + random.randbytes(16)).hexdigest().upper()


def generate_sensors_data(distinct_id):
    """生成sensorsdata2015jssdkcross Cookie"""
    data = {
        "distinct_id": distinct_id,
        "first_id": "",
        "props": {},
        "identities": f"eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMTljMWFkNWNiOTc1ZjctMDNkMDRmYzhlZmVhYTgtMjY0ZTI5NjYtMTI5NjAwMC0xOWMxYWQ1Y2I5ODZjYyJ9",
        "$device_id": distinct_id
    }
    return quote(json.dumps(data, separators=(',', ':')))


def get_enhanced_device_config():
    """获取增强版设备配置"""
    device = random.choice(ENHANCED_DEVICE_POOL)
    chrome_version = random.choice(CHROME_VERSIONS)

    # 生成设备指纹（保持格式一致性）
    fingerprint = f"ffffffff-{binascii.b2a_hex(random.randbytes(2)).decode()}-{binascii.b2a_hex(random.randbytes(2)).decode()}-ffff-ffff{binascii.b2a_hex(random.randbytes(4)).decode()}"
    android_id = binascii.b2a_hex(random.randbytes(8)).decode()

    # 构造浏览器UA
    browser_ua = (
        f"Mozilla/5.0 (Linux; Android {device['sys_ver']}; {device['ua_model']} "
        f"Build/{device['build']}; wv) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Version/4.0 Chrome/{chrome_version} Mobile Safari/537.36"
    )

    return {
        "brand": device['brand'],
        "model": device['model'],
        "sys_ver": device['sys_ver'],
        "ua_model": device['ua_model'],
        "build": device['build'],
        "fingerprint": fingerprint,
        "android_id": android_id,
        "oaid": str(uuid.uuid4()),
        "trace_id": generate_trace_id(),
        "user_agent": "okhttp/3.8.0",
        "browser_ua": browser_ua,
        "chrome_version": chrome_version,
    }


# ==================== 加密核心逻辑 ====================

def aes_encrypt(text, key_hex, iv_hex):
    """AES-CBC加密"""
    key = binascii.unhexlify(key_hex)
    iv = binascii.unhexlify(iv_hex)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ct_bytes = cipher.encrypt(pad(text.encode('utf-8'), AES.block_size))
    return base64.b64encode(ct_bytes).decode('utf-8')


def rsa_encrypt(text, public_key_b64):
    """RSA加密"""
    key_data = base64.b64decode(public_key_b64)
    public_key = RSA.import_key(key_data)
    cipher = PKCS1_v1_5.new(public_key)
    ct_bytes = cipher.encrypt(text.encode('utf-8'))
    return base64.b64encode(ct_bytes).decode('utf-8')


def generate_p0_k0_dynamic(vtoken, p0_params):
    """生成p0和k0加密参数"""
    aes_key_hex = binascii.b2a_hex(random.randbytes(32)).decode()
    aes_iv_hex = binascii.b2a_hex(random.randbytes(16)).decode()
    vtoken_b64 = base64.b64encode(vtoken.encode()).decode()

    p0_plain = (
        f"app_v--{p0_params['app_v']}||brand--{p0_params['brand']}||"
        f"p_type--{p0_params['p_type']}||sdk_v--{p0_params['sdk_v']}||"
        f"sys--{p0_params['sys']}||sys_ver--{p0_params['sys_ver']}||"
        f"vtoken--{vtoken_b64}||wm--{p0_params['wm']}"
    )

    p0 = aes_encrypt(p0_plain, aes_key_hex, aes_iv_hex)
    key_bin = binascii.unhexlify(aes_key_hex)
    iv_bin = binascii.unhexlify(aes_iv_hex)
    rsa_plain = base64.b64encode(key_bin).decode(
    ) + "\n" + base64.b64encode(iv_bin).decode()
    k0 = rsa_encrypt(rsa_plain, RSA_PUBLIC_KEY)
    return p0, k0


# ==================== 验证码处理 ====================

def solve_geetest_v4(captcha_id, proxy=None):
    """通过自定义接口破解极验v4验证码"""
    print(f"[*] 正在请求自定义接口解决极验 v4: {captcha_id}")

    # 接口地址
    # api_url = "http://192.144.154.164:8989"
    api_url = "http://127.0.0.1:8989"
    # 构造代理字符串 (假设 proxy 是一个字典，如 {'http': 'http://user:pass@ip:port'})
    # 如果没有代理，可以传空字符串或其他约定值
    proxy_str = ""
    if proxy and isinstance(proxy, dict):
        # 优先取 https，其次 http
        proxy_url = proxy.get("https") or proxy.get("http")
        if proxy_url:
            # 简单的处理，具体格式需根据接口要求调整
            # 假设接口接受完整的代理URL，但需要去掉协议头
            proxy_str = proxy_url.replace(
                "http://", "").replace("https://", "")

    # 提交内容：火币,代理,captcha_id
    # 注意：这里直接发送逗号分隔的字符串，还是JSON？
    # 根据用户描述 "提交内容：火币,代理,captcha_id"，推测是 POST raw body 或 text/plain
    # 但通常 API 接受 JSON 或 Form Data。
    # 假设是 POST 请求，body 为 "火币,{proxy},{captcha_id}"

    payload = f"火币,{proxy_str},{captcha_id}"
    print(f"[DEBUG] 极验提交参数 (Payload): {payload}")

    try:
        import requests
        # 尝试发送请求
        # 注意：这里没有指定 content-type，视服务端要求而定
        # 注意：这里明确不使用任何代理访问自定义接口，因为它是内网/直连服务
        resp = requests.post(api_url, data=payload.encode(
            'utf-8'), timeout=60, proxies={"http": None, "https": None})

        # 打印原始响应内容以便调试
        resp_text = resp.text
        # print(f"[DEBUG] 自定义接口响应 ({resp.status_code}): {resp_text[:200]}") # 只打印前200字符

        if resp.status_code == 200:
            # 尝试解析 JSON
            try:
                result = resp.json()
                if isinstance(result, dict):
                    # 优先检查最外层是否有 status: success
                    if result.get("status") == "success" and "data" in result:
                        data = result["data"]
                        # 检查 data 中是否包含必要的 seccode 字段 (极验 V4 关键)
                        if isinstance(data, dict) and "seccode" in data:
                            seccode = data["seccode"]
                            # 构造 solution 字典
                            solution = {
                                "captcha_id": seccode.get("captcha_id"),
                                "lot_number": seccode.get("lot_number"),
                                "pass_token": seccode.get("pass_token"),
                                "gen_time": seccode.get("gen_time"),
                                "captcha_output": seccode.get("captcha_output")
                            }
                            print("[+] 自定义接口返回成功 (V4 seccode)")
                            return solution

                        # 兼容旧逻辑：直接在 data 中查找 (如果不是嵌套 seccode)
                        elif "lot_number" in data and "pass_token" in data:
                            print("[+] 自定义接口返回成功 (Standard Data)")
                            return data

                    # 检查是否包含必要的字段 (扁平结构)
                    if "lot_number" in result and "pass_token" in result:
                        print("[+] 自定义接口返回成功 (Flat JSON)")
                        return result

                print(f"[!] 自定义接口返回 JSON 格式未知: {result}")
                return result  # 尝试直接返回
            except json.JSONDecodeError:
                # 如果不是 JSON，尝试解析纯文本
                # 假设返回格式为: lot_number|pass_token|gen_time|captcha_output
                # 或者其他分隔符格式
                print("[*] 响应不是 JSON，尝试作为纯文本处理")

                # 这里需要知道非 JSON 格式的具体结构
                # 暂时只能打印并返回 None，等待您提供响应样本
                return None

        else:
            print(f"[!] 自定义接口请求失败: {resp.status_code} - {resp_text}")
            return None

    except Exception as e:
        print(f"[!] 自定义接口异常: {e}")
        return None


def get_email_auth_code(email_user, email_pwd, max_retries=100, client_id=None, refresh_token=None, email_type='self', keyword=None):
    """
    从邮件中获取验证码，先查询收件箱，再查询垃圾箱
    :param keyword: 可选，必须包含的关键字 (如 '您正在尝试【开启GA】')
    """
    print(f"[*] 正在获取验证码 (账号: {email_user})...")
    if keyword:
        print(f"[*] 过滤关键字: {keyword}")
    print(f"[*] 将尝试 {max_retries} 次获取邮件，每次间隔 1 秒")
    print(f"[*] 每次尝试会先查询收件箱，再查询垃圾箱")

    # 根据账号类型选择验证码获取方式
    if email_type == 'microsoft' and client_id and refresh_token:
        print("[*] 使用 youx.py 获取微软邮箱验证码...")
        try:
            # 导入 youx.py 模块
            import youx

            for attempt in range(max_retries):
                print(f"[*] 尝试获取邮件 ({attempt + 1}/{max_retries})...")

                # 1. 先查询收件箱
                print("[*] 查询收件箱...")
                mail_content = youx.get_mail(
                    email=email_user,
                    client_id=client_id,
                    refresh_token=refresh_token,
                    from_junk=False,
                    use_graph=True
                )

                # 从邮件内容中提取验证码
                code = None
                if mail_content:
                    print("[+] 成功获取收件箱邮件")
                    # 预处理邮件内容，移除可能的干扰字符
                    processed_content = mail_content

                    # 关键字过滤
                    if keyword and keyword not in processed_content:
                        print(f"[!] 邮件未包含关键字 '{keyword}'，跳过")
                        code = None
                    else:
                        # 修改正则表达式，使其能够处理 HTML 格式的邮件内容
                        # 允许 "您的验证码是:" 和验证码之间有任意数量的字符（包括换行符和 HTML 标签）
                        patterns = [
                            r'您的验证码是[:：\s]*(?:<[^>]+>|\s)*([0-9]{6})',
                            # 新增规则，支持HTML标签
                            r'验证码为[:：\s]*(?:<[^>]+>|\s)*([0-9]{6})'
                            # r'验证码[:：\s]*[\s\S]*?([0-9]{6})'
                            # 匹配独立的6位数字，前后不能是字母、数字或@符号 (防止匹配到邮箱中的数字)

                        ]

                        for pattern in patterns:
                            match = re.search(
                                pattern, processed_content, re.IGNORECASE | re.DOTALL)
                            if match:
                                # 提取捕获组的内容
                                code = match.group(1)
                                print(f"[+] 从收件箱成功匹配到验证码: {code}")
                                return code

                    if not code:
                        print("[!] 收件箱邮件中未找到验证码")
                        # print(f"[DEBUG] 邮件内容预览: {mail_content[:300]}...") # 避免刷屏
                else:
                    print("[!] 获取收件箱邮件失败")

                # 2. 如果收件箱没有，查询垃圾箱
                if not code:
                    print("[*] 查询垃圾箱...")
                    mail_content = youx.get_mail(
                        email=email_user,
                        client_id=client_id,
                        refresh_token=refresh_token,
                        from_junk=True,
                        use_graph=True
                    )

                    if mail_content:
                        print("[+] 成功获取垃圾箱邮件")
                        # 预处理邮件内容，移除可能的干扰字符
                        processed_content = mail_content

                        # 关键字过滤
                        if keyword and keyword not in processed_content:
                            print(f"[!] 邮件未包含关键字 '{keyword}'，跳过")
                            code = None
                        else:
                            # 修改正则表达式，使其能够处理 HTML 格式的邮件内容
                            # 允许 "您的验证码是:" 和验证码之间有任意数量的字符（包括换行符和 HTML 标签）
                            patterns = [
                                r'您的验证码是[:：\s]*(?:<[^>]+>|\s)*([0-9]{6})',
                                # 新增规则，支持HTML标签
                                r'验证码为[:：\s]*(?:<[^>]+>|\s)*([0-9]{6})'
                                # r'验证码[:：\s]*[\s\S]*?([0-9]{6})'
                                # 匹配独立的6位数字，前后不能是字母、数字或@符号

                            ]

                            for pattern in patterns:
                                match = re.search(
                                    pattern, processed_content, re.IGNORECASE | re.DOTALL)
                                if match:
                                    # 提取捕获组的内容
                                    code = match.group(1)
                                    print(f"[+] 从垃圾箱成功匹配到验证码: {code}")
                                    return code

                        if not code:
                            print("[!] 垃圾箱邮件中未找到验证码")
                            # print(f"[DEBUG] 邮件内容预览: {mail_content[:300]}...")
                    else:
                        print("[!] 获取垃圾箱邮件失败")

                # 每次尝试后等待1秒
                if attempt < max_retries - 1:
                    print("[*] 等待 1 秒后重试...")
                    time.sleep(5)
        except Exception as e:
            print(f"[!] 使用 youx.py 获取邮件异常: {e}")
    else:
        print("[*] 使用老接口获取自建邮箱验证码...")
        try:
            import requests
            for attempt in range(max_retries):
                print(f"[*] 尝试获取验证码 ({attempt + 1}/{max_retries})...")
                try:
                    # 使用老接口获取验证码
                    response = requests.get(
                        GET_CODE_API,
                        params={"yhm": email_user, "mm": email_pwd},
                        timeout=10
                    )
                    result = response.text.strip()
                    # 提取验证码，只使用中文格式的正则表达式匹配方式
                    code = None
                    if result:
                        print("[+] 成功获取邮件内容")

                        # 关键字过滤
                        if keyword and keyword not in result:
                            print(f"[!] 邮件未包含关键字 '{keyword}'，跳过")
                            code = None
                        else:
                            # 修改正则表达式，使其能够处理 HTML 格式的邮件内容
                            # 允许 "您的验证码是:" 和验证码之间有任意数量的字符（包括换行符和 HTML 标签）
                            patterns = [
                                r'您的验证码是[:：\s]*(?:<[^>]+>|\s)*([0-9]{6})',
                                # 新增规则，支持HTML标签
                                r'验证码为[:：\s]*(?:<[^>]+>|\s)*([0-9]{6})'
                                # r'验证码[:：\s]*[\s\S]*?([0-9]{6})'
                                # 匹配独立的6位数字，前后不能是字母、数字或@符号

                            ]

                            for pattern in patterns:
                                match = re.search(
                                    pattern, result, re.IGNORECASE | re.DOTALL)
                                if match:
                                    code = match.group(1)
                                    print(f"[+] 从老接口成功获取验证码: {code}")
                                    return code

                        if not code:
                            print("[!] 邮件中未找到验证码")
                    else:
                        print(f"[!] 老接口返回: {result}")
                except Exception as e:
                    print(f"[!] 老接口请求异常: {e}")
                # 每次尝试后等待1秒
                if attempt < max_retries - 1:
                    print("[*] 等待 1 秒后重试...")
                    time.sleep(1)
        except Exception as e:
            print(f"[!] 使用老接口获取验证码异常: {e}")

    print("[!] 获取验证码超时")
    return None


def verify_email(email, password, client_id=None, refresh_token=None, email_type='self'):
    """
    验证邮箱可用性
    :param email: 邮箱地址
    :param password: 密码
    :param client_id: Client ID (微软)
    :param refresh_token: Refresh Token (微软)
    :param email_type: 类型 ('self' 或 'microsoft')
    :return: (bool, str) -> (是否可用, 信息)
    """
    if email_type == 'microsoft':
        if not client_id or not refresh_token:
            return False, "缺少OAuth凭证"

        try:
            import youx
            client = youx.MicrosoftMailClient(email, client_id, refresh_token)

            # 1. 验证 Token 刷新
            if not client._refresh_access_token():
                return False, "Token刷新失败"

            # 2. 验证邮件获取（优先使用 Graph API）
            mail = client.get_mail(use_graph=True)
            if not mail:
                # 如果 Graph API 失败，尝试 IMAP
                if not client._connect_imap():
                    return False, "邮件获取失败"

            client.close()
            return True, "验证成功"
        except ImportError:
            return False, "缺少 youx.py 模块"
        except Exception as e:
            return False, f"异常: {str(e)}"

    else:
        # 自建/老接口验证
        try:
            import requests
            # 尝试连接接口
            response = requests.get(
                GET_CODE_API,
                params={"yhm": email, "mm": password},
                timeout=10
            )

            if response.status_code == 200:
                # 只要接口通了且没报错，暂时认为可用
                # 注意：具体业务错误码未知，仅根据连通性判断
                return True, "接口连接成功"
            else:
                return False, f"接口状态码: {response.status_code}"

        except Exception as e:
            return False, f"接口请求异常: {str(e)}"

# ==================== 火币客户端类（增强反检测版 V3） ====================


class HuobiClient:
    """火币API客户端 - 增强反检测版，模拟真实APP行为"""

    def __init__(self, device_config, proxies=None):
        self.device = device_config
        self.proxies = proxies

        # 创建Session（带TLS指纹伪装）
        if USE_TLS_CLIENT:
            # 使用 tls_client
            self.session = tls_client.Session(
                client_identifier=random.choice(
                    ["chrome_120", "chrome_119", "chrome_116"])
            )
            # 为 tls_client 添加兼容的请求方法
            self._patch_tls_client_session()
        elif USE_CURL_CFFI:
            # 随机选择TLS指纹
            impersonate_options = ["chrome120", "chrome119", "chrome116"]
            self.session = curl_requests.Session(
                impersonate=random.choice(impersonate_options))
        else:
            self.session = curl_requests.Session()

        if proxies:
            self.session.proxies = proxies

        # 设备标识（确保一致性）
        # 原逻辑：self.vtoken = self.device.get('android_id') or self.device.get('fingerprint', '')
        # 修改为：生成32位随机hex字符串，与测试脚本保持一致
        self.vtoken = binascii.b2a_hex(os.urandom(16)).decode()
        self.vtoken2 = binascii.b2a_hex(os.urandom(16)).decode()  # 新增 vtoken2
        self.fingerprint = self.device.get('fingerprint', '')

        # 动态生成的参数
        self.trace_id = generate_trace_id()
        self.ctx_id = generate_ctx_id()
        self.vulcan_uuid = generate_vulcan_uuid()
        self.urid = generate_urid()
        # hb_uc_ua: 随机生成一个 32 位的 hex 字符串 (模拟 MD5 格式)
        self.hb_uc_ua = binascii.b2a_hex(os.urandom(16)).decode()

        # 认证Token
        self.hb_uc_token = None
        self.hb_pro_token = None
        self.uid = None

        # 邀请码
        self.invite_code = None

        # GA Key
        self.ga_key = "NONE"

        # 请求计数器（用于模拟真实行为）
        self.request_count = 0
        self.session_start_time = time.time()

        # 功能标志
        self.enable_get_invite_code = True
        self.enable_delete_htx_emails = True

        # Cookie管理
        self._init_cookies()

        # 构建请求头
        self._build_headers()

    def _patch_tls_client_session(self):
        """为 tls_client.Session 添加兼容的请求方法，处理 timeout 参数"""
        original_get = self.session.get
        original_post = self.session.post

        def patched_get(url, **kwargs):
            # 移除 timeout 参数，tls_client 不支持
            timeout = kwargs.pop('timeout', None)
            return original_get(url, **kwargs)

        def patched_post(url, **kwargs):
            # 移除 timeout 参数，tls_client 不支持
            timeout = kwargs.pop('timeout', None)
            return original_post(url, **kwargs)

        self.session.get = patched_get
        self.session.post = patched_post

    def _init_cookies(self):
        """初始化Cookie"""
        self.cookies = {
            'HB-VULCAN-UUID': self.vulcan_uuid,
            'HB-UC-UA': self.hb_uc_ua,
            'sajssdk_2015_cross_new_user': '1',
            'sensorsdata2015jssdkcross': generate_sensors_data(self.fingerprint),
            'URID': self.urid,
        }

    def _update_auth_cookies(self):
        """更新认证相关的Cookie"""
        if self.hb_uc_token:
            self.cookies['HB-UC-TOKEN'] = self.hb_uc_token
            self.cookies['HB_SSO'] = f'"{self.hb_uc_token}"'
        if self.hb_pro_token:
            self.cookies['HB-PRO-TOKEN'] = self.hb_pro_token

    def _build_headers(self):
        """构建请求头"""
        browser_ua = self.device.get('browser_ua',
                                     f'Mozilla/5.0 (Linux; Android {self.device.get("sys_ver", "14")}; '
                                     f'{self.device.get("model", "SM-A528N")} Build/SP1A.210812.016; wv) '
                                     f'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.144 Mobile Safari/537.36')

        # 1. 注册相关接口的请求头（原生APP风格）
        self.register_headers = {
            'User-Agent': 'okhttp/3.8.0',
            'accept-language': 'zh-CN',
            'apptype': '1',
            'huobi-app-client': '2',
            'huobi-app-version': '10.52.0',
            'huobi-app-version-code': '105200',
            'appversion': '105200',
            'huobi-timezone': 'GMT+08:00',
            'terminalid': '1',
            'vop': '0',
            'device-v-token': self.fingerprint,
            'huobi-website': 'huobi.pro',
            'huobi-app-channel': str(INVITER_ID),
            'hb-country-id': '37',
            'hb-region-id': '41',
            'x-b3-traceid': self.trace_id,
            'huobi-client-platform': 'ANDROID',
            'huobi-client-fingerprint': self.fingerprint,
            'hb-uc-ua': self.hb_uc_ua,
            'vtoken': self.vtoken,
            'content-type': 'application/json; charset=UTF-8',
            'accept-encoding': 'gzip',
        }

        # 2. 业务相关接口的请求头（WebView风格）
        self.business_headers = {
            'User-Agent': f'BigHuobi/10.52.0 {browser_ua} HB_ENV ({{"theme":"0","global_api":"{API_DOMAIN_L10N}"}})',
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN',
            'vtoken': self.vtoken,
            'webmark': 'v10003',
            'x-requested-with': 'pro.huobi',
            'content-type': 'application/json;charset=UTF-8',
            'accept-encoding': 'gzip, deflate',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-mode': 'cors',
            'sec-fetch-dest': 'empty',
        }

    def _get_cookie_string(self):
        """获取Cookie字符串"""
        self._update_auth_cookies()
        return '; '.join([f'{k}={v}' for k, v in self.cookies.items()])

    def _get_register_headers(self):
        """获取注册相关接口的请求头（原生APP风格）"""
        headers = self.register_headers.copy()
        headers['x-b3-traceid'] = generate_trace_id()  # 每次请求生成新的trace_id
        if self.hb_uc_token:
            headers['hb-uc-token'] = self.hb_uc_token
        if self.uid:
            headers['hb-ctx-id'] = str(self.uid)
        return headers

    def _get_business_headers(self, with_origin=True):
        """获取业务相关接口的请求头（WebView风格）"""
        headers = self.business_headers.copy()
        if with_origin:
            headers['origin'] = f'https://{API_DOMAIN}'
            headers['referer'] = f'https://{API_DOMAIN}/zh-cn/welfare?utm_source=hometop&userAgent=M%3Ahuobiapp%3Aphone%3Aandroid'
        headers['cookie'] = self._get_cookie_string()
        if self.hb_uc_token:
            headers['hb-uc-token'] = self.hb_uc_token
        if self.hb_pro_token:
            headers['hb-pro-token'] = self.hb_pro_token
        return headers

    # ==================== 【新增】ABTest请求（模拟真实APP行为） ====================

    def send_abtest_request(self):
        """
        发送abtest请求
        根据HAR分析，真实APP会在关键操作前后发送abtest请求
        """
        url = f"https://{API_DOMAIN_L10N}/-/x/uc/uc/open/auth_code_login_register/abtest"
        headers = self._get_register_headers()
        data = {
            "scene": 1,
            "fingerprint": self.fingerprint,
            "vtoken": self.vtoken
        }
        try:
            micro_delay()
            self.session.post(url, headers=headers, json=data, timeout=10)
            self.request_count += 1
        except:
            pass  # abtest请求失败不影响主流程

    # ==================== 预热请求序列（增强版） ====================

    def warmup(self):
        """执行预热请求序列，模拟APP启动（优化后）"""
        print("[*] 执行预热请求序列...")

        # 只保留必要的预热请求
        warmup_sequence = [
            # (URL, 方法, 描述, 延迟类型)
            (f"https://{API_DOMAIN}/status", "GET", "检查服务状态", "micro"),
            (f"https://{API_DOMAIN_L10N}/-/x/pro/netinfo",
             "GET", "获取网络信息", "micro"),
            (f"https://{API_DOMAIN_L10N}/-/x/hbg/v1/mgt/config/default/list",
             "GET", "获取默认配置", "micro"),
        ]

        headers = self._get_register_headers()

        for url, method, desc, delay_type in warmup_sequence:
            try:
                if delay_type == "micro":
                    micro_delay()
                elif delay_type == "short":
                    short_delay()

                if method == "GET":
                    self.session.get(url, headers=headers, timeout=10)
                self.request_count += 1
                print(f"  [预热] {desc} ✓")
            except Exception as e:
                print(f"  [预热] {desc} ✗")

        # 发送abtest请求
        self.send_abtest_request()

        short_delay()
        print("[+] 预热完成")

    # ==================== 背景请求 ====================

    def background_request(self, request_type="config"):
        """执行背景请求，模拟真实APP行为（优化后）"""
        background_apis = {
            "config": [
                f"https://{API_DOMAIN_L10N}/-/x/hbg/v1/hbg/open/biz/control/config",
                f"https://{API_DOMAIN_L10N}/-/x/pro/v2/settings/common/symbols",
            ],
            "user": [
                f"https://{API_DOMAIN}/-/x/uc/uc/open/user/get",
            ],
            "data": [
                f"https://{API_DOMAIN}/-/x/hbg/v1/hbg/open/data/collection",
            ],
            "otc": [
                f"https://{API_DOMAIN_L10N}/-/x/otc/v1/trade/fast/config/list",
            ]
        }

        apis = background_apis.get(request_type, background_apis["config"])

        # 随机选择1个API请求
        selected_apis = random.sample(
            apis, min(len(apis), 1))

        for url in selected_apis:
            try:
                headers = self._get_register_headers()
                # 移除延迟，直接请求
                self.session.get(url, headers=headers, timeout=3)
                self.request_count += 1
            except:
                pass

    # ==================== 注册相关 ====================

    def preliminary_check(self, email):
        """预检邮箱是否可用"""
        # 发送abtest请求
        self.send_abtest_request()

        url = f"https://{API_DOMAIN_L10N}/-/x/uc/uc/open/register/preliminary/check"
        data = {"way": "WEB", "email": email}
        headers = self._get_register_headers()
        try:
            short_delay()
            resp = self.session.post(
                url, headers=headers, json=data, timeout=15)
            result = resp.json()
            self.request_count += 1
            print(f"[DEBUG] 预检响应: {json.dumps(result, ensure_ascii=False)}")
            return result
        except Exception as e:
            print(f"[!] 预检异常: {e}")
            return {"success": False, "message": "网络异常"}

    def get_risk_control(self, email):
        """获取风控验证参数"""
        # 执行背景请求
        self.background_request("config")

        vhash = hashlib.md5(self.vtoken.encode()).hexdigest()
        url = f"https://{API_DOMAIN_L10N}/-/x/uc/uc/open/risk/control?vHash={vhash}"

        p0_params = {
            "app_v": "10.52.0",
            "brand": self.device.get('brand', 'Xiaomi'),
            "p_type": "android",
            "sdk_v": "33",
            "sys": "android",
            "sys_ver": self.device.get('sys_ver', '13'),
            "wm": "1"
        }

        p0, k0 = generate_p0_k0_dynamic(self.vtoken, p0_params)
        data = {
            "p0": p0,
            "login_name": email,
            "cHash": binascii.b2a_hex(random.randbytes(16)).decode(),
            "k0": k0,
            "fingerprint": self.fingerprint,
            "source": 5,
            "vToken": self.vtoken,
            "version": "4",
            "scene": 1
        }
        headers = self._get_register_headers()
        try:
            medium_delay()
            resp = self.session.post(
                url, headers=headers, json=data, timeout=15)
            self.request_count += 1
            return resp.json()
        except Exception as e:
            print(f"[!] get_risk_control异常: {e}")
            return {}

    def send_email_code(self, email, solution):
        """发送邮箱验证码"""
        # 发送多次abtest请求（模拟HAR中的行为）
        for _ in range(random.randint(2, 4)):
            self.send_abtest_request()
            abtest_interval()

        url = f"https://{API_DOMAIN_L10N}/-/x/uc/uc/open/email_code/send"
        data = {
            "use_type": "AUTH_CODE_LOGIN_REGISTER",
            "captcha_param": {
                "params": {
                    "captcha_id": solution["captcha_id"],
                    "lot_number": solution["lot_number"],
                    "pass_token": solution["pass_token"],
                    "gen_time": solution["gen_time"],
                    "captcha_output": solution["captcha_output"]
                },
                "type": "3"
            },
            "email": email,
            "scene": 1
        }
        headers = self._get_register_headers()
        headers["huobi-business"] = "PRO"
        try:
            short_delay()
            resp = self.session.post(
                url, headers=headers, json=data, timeout=15)
            self.request_count += 1
            return resp.json()
        except Exception as e:
            print(f"[!] send_email_code异常: {e}")
            return {}

    def verify_auth_code(self, email, auth_code):
        """验证邮箱验证码"""
        # 发送abtest请求
        self.send_abtest_request()

        url = f"https://{API_DOMAIN_L10N}/-/x/uc/uc/open/login_register/verify_auth_code"
        headers = self._get_register_headers()
        data = {
            "vtoken": self.vtoken,
            "fingerprint": self.fingerprint,
            "email": email,
            "way": "APP_HUOBI_PRO",
            "auth_code": auth_code
        }
        try:
            short_delay()
            resp = self.session.post(
                url, headers=headers, json=data, timeout=15)
            self.request_count += 1
            return resp.json()
        except Exception as e:
            print(f"[!] verify_auth_code异常: {e}")
            return {}

    def register(self, email, password, auth_code, auth_token, client_id=None, refresh_token=None, email_type='self', invite_code=None):
        """完成注册"""
        # 执行背景请求
        self.background_request("config")

        url = f"https://{API_DOMAIN_L10N}/-/x/uc/uc/open/auth_code/register"
        password_hash = hashlib.md5(
            (password + "hello, moto").encode()).hexdigest()

        timestamp = int(time.time() * 1000)
        random_num = random.randint(10**18, 10**19 - 1)
        af_id = f"{timestamp}-{random_num}"

        data = {
            "inviter_id": INVITER_ID,
            "login_ext_data": {
                "af_app_id": "pro.huobi",
                "af_device_id": hashlib.sha256(self.fingerprint.encode()).hexdigest(),
                "af_device_id_type": "oaid",
                "af_id": af_id,
                "app_instance_id": self.device.get('android_id', hashlib.md5(self.fingerprint.encode()).hexdigest())
            },
            "client_platform": "ANDROID",
            "version": "2",
            "way": "APP_HUOBI_PRO",
            "auth_code": auth_code,
            "vtoken": self.vtoken,
            "password": password_hash,
            "ad_id": self.device.get('android_id', hashlib.md5(self.fingerprint.encode()).hexdigest()),
            "client_app": "HBG",
            "site_id": 2,
            "fingerprint": self.fingerprint,
            "password_level": 5,
            "invite_code": invite_code if invite_code else INVITE_CODE,
            "auth_token": auth_token,
            "client_version": "10.52.0",
            "email": email
        }

        headers = self._get_register_headers()

        try:
            medium_delay()
            resp = self.session.post(
                url, headers=headers, json=data, timeout=15)
            register_response = resp.json()
            self.request_count += 1

            if register_response.get("success"):
                self.hb_uc_token = register_response.get(
                    "data", {}).get("uc_token")
                self.uid = register_response.get("data", {}).get("uid")
                self._update_auth_cookies()
                print(f"[+] 注册成功，UID: {self.uid}")

                # 保存注册时的邮箱凭证，供后续GA绑定使用
                self.register_email_info = {
                    "email": email,
                    "password": password,
                    "client_id": client_id,
                    "refresh_token": refresh_token,
                    "email_type": email_type
                }

            return register_response
        except Exception as e:
            print(f"[!] register异常: {e}")
            return {}

    # ==================== 登录相关 ====================

    def get_ticket(self):
        """获取登录Ticket"""
        url = f"https://{API_DOMAIN_L10N}/-/x/uc/uc/open/ticket/get"
        headers = self._get_register_headers()
        headers['content-type'] = 'application/json;charset=UTF-8'

        try:
            short_delay()
            resp = self.session.get(url, headers=headers, timeout=15)
            result = resp.json()
            self.request_count += 1
            if result.get("success") or result.get("code") == 200:
                ticket = result.get("data", {}).get("ticket")
                print(
                    f"[+] 获取Ticket成功: {ticket[:20]}..." if ticket else "[!] Ticket为空")
                return ticket
            else:
                print(f"[!] 获取Ticket失败: {result}")
                return None
        except Exception as e:
            print(f"[!] get_ticket异常: {e}")
            return None

    def login_with_ticket(self, ticket):
        """使用Ticket登录，获取HB-PRO-TOKEN"""
        url = f"https://{API_DOMAIN_L10N}/-/x/pro/v1/users/login?ticket={ticket}"
        headers = self._get_register_headers()
        headers['content-type'] = 'application/json;charset=UTF-8'
        data = {"ticket": ticket}

        try:
            short_delay()
            resp = self.session.post(
                url, headers=headers, json=data, timeout=15)
            result = resp.json()
            self.request_count += 1
            if result.get("status") == "ok":
                self.hb_pro_token = result.get("data", {}).get("token")
                self._update_auth_cookies()
                print(
                    f"[+] 登录成功，获取到 HB-PRO-TOKEN: {self.hb_pro_token[:30]}...")
                return True
            else:
                print(f"[!] 登录失败: {result}")
                return False
        except Exception as e:
            print(f"[!] login_with_ticket异常: {e}")
            return False

    def login(self):
        """完整登录流程"""
        print("[*] 开始登录流程...")
        self.background_request("user")
        ticket = self.get_ticket()
        if not ticket:
            return False
        return self.login_with_ticket(ticket)

    # ==================== 签到相关 ====================

    def get_check_in_tasks(self):
        """获取签到任务列表"""
        r_param = ''.join(random.choices(
            'abcdefghijklmnopqrstuvwxyz0123456789', k=6))
        url = f"https://{API_DOMAIN}/-/x/wlf/v1/hbg/open/welfare/center/task/getCheckInTasks?r={r_param}"
        headers = self._get_business_headers(with_origin=False)
        try:
            short_delay()
            resp = self.session.get(url, headers=headers, timeout=15)
            result = resp.json()
            self.request_count += 1
            if result.get("code") == 200:
                return result.get("data", [])
            else:
                print(f"[!] 获取签到任务失败: {result}")
                return []
        except Exception as e:
            print(f"[!] get_check_in_tasks异常: {e}")
            return []

    def get_novice_tasks(self):
        """获取新手任务列表"""
        max_retries = 2  # 最多重试 2 次
        retry_count = 0

        while retry_count <= max_retries:
            r_param = ''.join(random.choices(
                'abcdefghijklmnopqrstuvwxyz0123456789', k=6))
            url = f"https://{API_DOMAIN}/-/x/wlf/v1/hbg/open/welfare/center/task/v2/getNoviceTasks?r={r_param}"
            headers = self._get_business_headers(with_origin=False)
            try:
                short_delay()
                resp = self.session.get(url, headers=headers, timeout=15)
                result = resp.json()
                self.request_count += 1
                if result.get("code") == 200:
                    return result.get("data", {})
                else:
                    print(f"[!] 获取新手任务失败: {result}")
                    retry_count += 1
                    if retry_count > max_retries:
                        return {}
            except Exception as e:
                print(f"[!] get_novice_tasks异常: {e}")
                retry_count += 1
                if retry_count > max_retries:
                    return {}
                print(f"[*] 正在重试 ({retry_count}/{max_retries})...")
                time.sleep(2)  # 延迟 2 秒后重试

        return {}

    def user_sign_in(self, user_task_id):
        """执行签到"""
        url = f"https://{API_DOMAIN}/-/x/hbg/v1/open/taskcenter/userSignIn"
        headers = self._get_business_headers()
        data = {"userTaskId": user_task_id}
        try:
            short_delay()
            resp = self.session.post(
                url, headers=headers, json=data, timeout=15)
            result = resp.json()
            self.request_count += 1
            if result.get("code") == 200 and result.get("success"):
                print(f"[+] 签到成功! userTaskId: {user_task_id}")
                return True
            else:
                print(f"[!] 签到失败: {result}")
                return False
        except Exception as e:
            print(f"[!] user_sign_in异常: {e}")
            return False

    def get_invite_code(self):
        """获取当前账号的邀请码 (多接口冗余版)"""
        headers = self._get_business_headers(False)

        # 接口 1: currentUid 接口 (首选)
        url1 = f"https://{API_DOMAIN}/-/x/hbg/uc/hbg/open/invite/v2/invite_code/default/get/currentUid"
        try:
            print(f"[*] 尝试接口1获取邀请码...")
            resp1 = self.session.get(url1, headers=headers, timeout=10).json()
            if resp1.get("success") and resp1.get("data"):
                invite_code = resp1.get("data", {}).get("invite_code")
                if invite_code:
                    print(f"[+] 接口1获取邀请码成功: {invite_code}")
                    self.invite_code = invite_code
                    return invite_code
            print(f"[-] 接口1获取失败: {resp1.get('message') or '无返回数据'}")
        except Exception as e:
            print(f"[!] 接口1异常: {e}")

        # 接口 2: getInviteUrl 接口 (备选)
        url2 = f"https://{API_DOMAIN}/-/x/hbg/uc/hbg/open/invite/v2/getInviteUrl"
        try:
            print(f"[*] 尝试接口2获取邀请码...")
            resp2 = self.session.get(url2, headers=headers, timeout=10).json()
            if resp2.get("success") and resp2.get("data"):
                # 格式通常为 "/invite/zh-cn/1f?invite_code=xxxxxx"
                url_str = resp2.get("data", "")
                if "invite_code=" in url_str:
                    invite_code = url_str.split(
                        "invite_code=")[-1].split("&")[0]
                    print(f"[+] 接口2获取邀请码成功: {invite_code}")
                    self.invite_code = invite_code
                    return invite_code
            print(f"[-] 接口2获取失败: {resp2.get('message') or '无返回数据'}")
        except Exception as e:
            print(f"[!] 接口2异常: {e}")

        # 接口 3: share config 接口 (最终兜底)
        url3 = f"https://{API_DOMAIN_L10N}/-/x/hbg/v1/hbg/open/share/v3/config"
        try:
            print(f"[*] 尝试接口3获取邀请码...")
            # 这个接口是 POST，且通常需要更多参数，我们尝试简单调用
            resp3 = self.session.post(url3, headers=headers, json={
                                      "source": "invite"}, timeout=10).json()
            if resp3.get("success") and resp3.get("data"):
                invite_code = resp3.get("data", {}).get("inviteCode")
                if invite_code:
                    print(f"[+] 接口3获取邀请码成功: {invite_code}")
                    self.invite_code = invite_code
                    return invite_code
            print(f"[-] 接口3获取失败: {resp3.get('message') or '无返回数据'}")
        except Exception as e:
            print(f"[!] 接口3异常: {e}")

        print("[!] 所有接口均未能获取邀请码")
        return None

    def draw_task_prize(self, user_task_id):
        """领取任务奖励/抽奖"""
        url = f"https://{API_DOMAIN}/-/x/wlf/v1/hbg/open/welfare/center/normalTask/drawTaskPrize"
        headers = self._get_business_headers()
        data = {"userTaskId": user_task_id}
        try:
            short_delay()
            resp = self.session.post(
                url, headers=headers, json=data, timeout=15)
            result = resp.json()
            self.request_count += 1
            if result.get("code") == 200 and result.get("success"):
                awards = result.get("data", {}).get("taskAwards", [])
                for award in awards:
                    count = award.get("count", 0)
                    currency = award.get(
                        "properties", {}).get("currency", "未知")
                    print(f"[+] 抽奖成功! 获得 {count} {currency.upper()}")
                return True
            else:
                print(f"[!] 抽奖失败: {result}")
                return False
        except Exception as e:
            print(f"[!] draw_task_prize异常: {e}")
            return False

    # ==================== GA绑定流程 (新增代码) ====================
    # 新增代码开始
    def _request_with_retry(self, method, url, **kwargs):
        """
        带重试机制的请求方法，专门用于处理 'connection forcibly closed' 等网络错误
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if method.upper() == "GET":
                    response = self.session.get(url, **kwargs)
                else:
                    response = self.session.post(url, **kwargs)
                return response
            except Exception as e:
                print(f"[!] 请求异常 (尝试 {attempt + 1}/{max_retries}): {e}")
                # 如果是最后一次尝试，抛出异常
                if attempt == max_retries - 1:
                    raise e
                # 遇到连接被重置等严重网络错误，尝试稍微延迟
                time.sleep(random.uniform(1.5, 3.0))
        return None

    def bind_ga_process(self, email=None, password=None, client_id=None, refresh_token=None, email_type='self', enable_delete_htx_emails=True):
        """
        执行GA绑定流程 (5步接口)
        :param email: 邮箱地址 (用于获取验证码)
        :param password: 邮箱密码
        :param client_id: 微软客户端ID
        :param refresh_token: 微软刷新令牌
        :param email_type: 邮箱类型 ('self' 或 'microsoft')
        :param enable_delete_htx_emails: 是否在绑定GA后删除HTX邮件
        """
        print("\n" + "-" * 40)
        print("抽奖完成，开始执行GA绑定流程")
        print("-" * 40)

        # 这里的URL需要根据实际情况确认，暂基于上下文推测
        # 基础域名使用 API_DOMAIN_L10N (l10n-pro.88maru.com)
        base_url = f"https://{API_DOMAIN_L10N}"

        try:
            # ------------------------------------------------------------------
            # 第1步: 获取 ga_key
            # ------------------------------------------------------------------
            print("[GA-1] 正在获取 ga_key...")
            # 根据提供的 CURL 更新 URL: /-/x/uc/uc/open/ga/generate?type=ASSET_GA
            url_1 = f"{base_url}/-/x/uc/uc/open/ga/generate?type=ASSET_GA"
            headers_1 = self._get_register_headers()

            # 发送 GET 请求 (使用重试机制)
            resp_1 = self._request_with_retry(
                "GET", url_1, headers=headers_1, timeout=10)
            print(f"[GA-1] 响应状态码: {resp_1.status_code}")
            print(f"[GA-1] 响应内容: {resp_1.text[:200]}...")

            res_json_1 = resp_1.json()
            ga_key = None
            if res_json_1.get("success") and res_json_1.get("data"):
                ga_key = res_json_1["data"].get("ga_key")
                self.ga_key = ga_key
                print(f"[GA-1] 获取成功, ga_key: {ga_key}")
            else:
                print(f"[GA-1] 获取失败: {res_json_1.get('message')}")
                # 即使失败也继续尝试后续步骤(按需求)，但后续可能会因缺参失败

            short_delay()

            # ------------------------------------------------------------------
            # 第2步: 提交 ga_code 获取 token
            # ------------------------------------------------------------------
            print("[GA-2] 正在提交 ga_code 获取 token...")
            # 根据提供的 CURL 更新 URL: /-/x/uc/uc/open/ga_code/verify
            url_2 = f"{base_url}/-/x/uc/uc/open/ga_code/verify"
            headers_2 = self._get_register_headers()

            # 【动态获取】生成 GA 验证码
            from ga_generator import get_ga_code
            ga_code_placeholder = get_ga_code(ga_key)
            if not ga_code_placeholder:
                print(f"[!] GA验证码生成失败，ga_key: {ga_key}")
                # 如果没有ga_code，后续必然失败，这里可以选择return或继续尝试
                # 为了流程完整性，暂且让其继续，或者设为默认值
                ga_code_placeholder = "000000"
            else:
                print(f"[GA-2] 生成验证码: {ga_code_placeholder}")

            data_2 = {"ga_code": ga_code_placeholder}

            # 使用重试机制
            resp_2 = self._request_with_retry(
                "POST", url_2, headers=headers_2, json=data_2, timeout=10)
            print(f"[GA-2] 响应状态码: {resp_2.status_code}")
            print(f"[GA-2] 响应内容: {resp_2.text[:200]}...")

            res_json_2 = resp_2.json()
            ga_token = None
            if res_json_2.get("success") and res_json_2.get("data"):
                ga_token = res_json_2["data"].get("token")
                print(f"[GA-2] 获取成功, token: {ga_token}")
            else:
                print(f"[GA-2] 获取失败: {res_json_2.get('message')}")

            short_delay()

            # ------------------------------------------------------------------
            # 第3步: 发送邮箱验证码
            # ------------------------------------------------------------------
            # 调整步骤3: 发送邮箱验证码
            print("[GA-3] 正在发送邮箱验证码...")
            # 根据提供的 CURL 更新 URL: /-/x/uc/uc/open/email_code/send
            url_3 = f"{base_url}/-/x/uc/uc/open/email_code/send"
            headers_3 = self._get_register_headers()
            headers_3["huobi-business"] = "PRO"

            data_3 = {"use_type": "VERIFY_SETTING_POLICY_BIND_GA"}

            # 使用重试机制
            resp_3 = self._request_with_retry(
                "POST", url_3, headers=headers_3, json=data_3, timeout=10)
            print(f"[GA-3] 响应状态码: {resp_3.status_code}")
            print(f"[GA-3] 响应内容: {resp_3.text[:200]}...")

            short_delay()

            # ------------------------------------------------------------------
            # 第4步: 提交邮箱验证码获取 auth_token (验证策略)
            # ------------------------------------------------------------------
            print("[GA-4] 正在提交邮箱验证码获取 auth_token...")
            # 根据提供的 CURL 更新 URL: /-/x/uc/uc/open/security/strategy/verify
            url_4 = f"{base_url}/-/x/uc/uc/open/security/strategy/verify"
            headers_4 = self._get_register_headers()

            # 【动态获取】邮箱验证码
            if email and (password or (client_id and refresh_token)):
                print(f"[GA-4] 正在从邮箱 {email} 获取验证码...")

                # 判断接码方式
                actual_email_type = email_type
                if client_id and refresh_token:
                    # 如果有 client_id 和 refresh_token，强制使用 microsoft 模式
                    actual_email_type = 'microsoft'
                    print("[GA-4] 检测到微软OAuth凭证，将使用 youx.py (Microsoft) 获取验证码")
                else:
                    # 否则默认为 self (自建/老接口)
                    actual_email_type = 'self'
                    print("[GA-4] 将使用老接口 (Self-hosted) 获取验证码")

                # 模拟等待邮件到达
                human_typing_delay()
                email_code_placeholder = get_email_auth_code(
                    email,
                    password,
                    client_id=client_id,
                    refresh_token=refresh_token,
                    email_type=actual_email_type,
                    keyword="您正在尝试【开启GA】"  # 添加关键字过滤
                )
                if not email_code_placeholder:
                    print(f"[!] 获取邮箱验证码失败，使用默认值")
                    email_code_placeholder = "000000"
                else:
                    print(f"[GA-4] 获取验证码成功: {email_code_placeholder}")
            else:
                print(f"[!] 缺少邮箱凭证，无法自动获取验证码，使用默认占位符")
                email_code_placeholder = "354555"

            data_4 = {
                "email_code": email_code_placeholder,
                "use_type": "VERIFY_SETTING_POLICY_BIND_GA"
            }

            # 使用重试机制
            resp_4 = self._request_with_retry(
                "POST", url_4, headers=headers_4, json=data_4, timeout=10)
            print(f"[GA-4] 响应状态码: {resp_4.status_code}")
            print(f"[GA-4] 响应内容: {resp_4.text[:200]}...")

            res_json_4 = resp_4.json()
            auth_token = None
            if res_json_4.get("success") and res_json_4.get("data"):
                auth_token = res_json_4["data"].get("token")
                print(f"[GA-4] 获取成功, auth_token: {auth_token}")
            else:
                print(f"[GA-4] 获取失败: {res_json_4.get('message')}")

            short_delay()

            # ------------------------------------------------------------------
            # 第5步: 最终绑定 GA
            # ------------------------------------------------------------------
            print("[GA-5] 正在最终绑定 GA...")
            # 根据提供的 CURL 更新 URL: /-/x/uc/uc/open/asset_ga/bind
            # 注意: vHash 需要计算
            vhash = hashlib.md5(self.vtoken.encode()).hexdigest()
            url_5 = f"{base_url}/-/x/uc/uc/open/asset_ga/bind?vHash={vhash}"
            headers_5 = self._get_register_headers()

            # 准备加密参数 p0, k0
            p0_params = {
                "app_v": "10.52.0",
                "brand": self.device.get('brand', 'Xiaomi'),
                "p_type": "android",
                "sdk_v": "33",
                "sys": "android",
                "sys_ver": self.device.get('sys_ver', '13'),
                "wm": "1"
            }
            p0, k0 = generate_p0_k0_dynamic(self.vtoken, p0_params)

            data_5 = {
                "p0": p0,
                "ga_code": ga_code_placeholder,  # 【需替换为实际值】
                "cHash": binascii.b2a_hex(random.randbytes(16)).decode(),
                "k0": k0,
                "enable_in_2fa": True,
                "ga_token": ga_token if ga_token else "PLACEHOLDER_TOKEN",  # 依赖步骤2
                "auth_token": auth_token if auth_token else "PLACEHOLDER_TOKEN",  # 依赖步骤4
                "vToken": self.vtoken
            }

            # 使用重试机制
            resp_5 = self._request_with_retry(
                "POST", url_5, headers=headers_5, json=data_5, timeout=10)
            print(f"[GA-5] 响应状态码: {resp_5.status_code}")
            print(f"[GA-5] 响应内容: {resp_5.text[:200]}...")

            if resp_5.json().get("success"):
                print("[GA-5] ★★★ GA绑定成功! ★★★")
            else:
                print(f"[GA-5] GA绑定失败: {resp_5.json().get('message')}")

        except Exception as e:
            print(f"[!] GA绑定流程异常: {e}")
            import traceback
            traceback.print_exc()

        print("\nGA绑定流程执行结束")

        # 绑定完GA后删除HTX邮件
        if enable_delete_htx_emails and email and (password or (client_id and refresh_token)):
            print("\n[*] GA绑定完成，开始清理HTX邮件...")
            try:
                # 导入 youx.py 模块
                import youx

                if email_type == 'microsoft' and client_id and refresh_token:
                    # 使用 youx.py 删除微软邮箱的HTX邮件
                    print(f"[*] 正在删除 {email} 的HTX邮件...")
                    # 创建 MicrosoftMailClient 实例
                    client = youx.MicrosoftMailClient(
                        email, client_id, refresh_token)
                    deleted_count = client.delete_htx_emails()
                    print(f"[+] 成功删除 {deleted_count} 封HTX邮件")
                else:
                    # 对于自建邮箱，暂时不处理
                    print("[*] 自建邮箱暂不支持自动删除邮件")
            except Exception as e:
                print(f"[!] 删除HTX邮件异常: {e}")
        elif not enable_delete_htx_emails:
            print("\n[*] 跳过删除HTX邮件操作")
        print("-" * 40)
    # 新增代码结束

    def turntable_draw(self, email=None):
        """执行大转盘抽奖 (隔离Session版，防止污染主登录状态)"""
        global airdrop_fail_count
        global max_airdrop_failures
        global airdrop_success_accounts
        global airdrop_success_lock

        activity_id = ACTIVITY_ID
        if not activity_id:
            print("[!] 未配置抽奖活动ID (ACTIVITY_ID)，跳过抽奖")
            return False

        print(f"[*] 开始执行大转盘抽奖 (隔离模式)，活动ID: {activity_id}")

        # --- 核心改进：创建隔离 Session ---
        if USE_TLS_CLIENT:
            isolated_session = tls_client.Session(
                client_identifier=self.session.client_identifier,
                random_tls_extension_order=True
            )
        else:
            isolated_session = curl_requests.Session(
                impersonate=getattr(self.session, 'impersonate', 'chrome110'))

        if self.proxies:
            isolated_session.proxies = self.proxies

        # 复制基础指纹 Cookie
        for k, v in self.session.cookies.items():
            if k.startswith('HB-VULCAN') or k in ['URID', 'sensorsdata2015jssdkcross']:
                isolated_session.cookies.set(k, v)

        isolated_headers_base = self._get_register_headers()

        max_draw_times = 5
        draw_success_flag = False
        reward_str_final = ""

        for n in range(max_draw_times):
            print(f"[*] 正在尝试第 {n+1} 次抽奖流程...")

            # 1. 获取主 APP 的 ticket
            url1 = f"https://{API_DOMAIN_L10N}/-/x/uc/uc/open/ticket/get"
            headers1 = isolated_headers_base.copy()
            try:
                short_delay()
                resp1 = isolated_session.get(url1, headers=headers1, timeout=15)
                try:
                    res1 = resp1.json()
                except Exception:
                    res1 = {}
                if not res1:
                    print(f"[-] 请求1返回空，重试...")
                    continue
                ticket1 = (res1.get("data") or {}).get("ticket")
                if not ticket1:
                    print(f"[-] 获取主APP ticket失败: {res1}，重试...")
                    continue
            except Exception as e:
                print(f"[-] 请求1异常: {e}")
                continue

            # 2. 获取微应用 新uc_token
            url2 = f"https://www.aglmt.com/-/x/uc/uc/open/token/get?hb_uc_ticket={ticket1}"
            headers2 = {
                "Content-Type": "application/json;charset=UTF-8",
                "Accept-Language": "zh-CN",
                "source": "web",
                "vToken": self.vtoken,
                "X-Requested-With": "pro.huobi",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "Referer": f"https://www.aglmt.com/microapps/zh-cn/double-invite-retail/round-about?activityId={activity_id}",
                "User-Agent": self.device.get('browser_ua', '')
            }
            try:
                short_delay()
                resp2 = isolated_session.get(url2, headers=headers2, timeout=15)
                try:
                    res2 = resp2.json()
                except Exception:
                    res2 = {}
                if not res2:
                    print(f"[-] 请求2返回空，重试...")
                    continue
                if str(res2.get("code")) == "200":
                    new_uc_token = (res2.get("data") or {}).get("token")
                else:
                    new_uc_token = None

                if not new_uc_token:
                    print(f"[-] 获取新uc_token失败: {res2}")
                    continue
            except Exception as e:
                print(f"[-] 请求2异常: {e}")
                continue

            # 3. 获取微应用 ticket
            url3 = "https://www.aglmt.com/-/x/uc/uc/open/ticket/get"
            headers3 = headers2.copy()
            headers3["HB-UC-TOKEN"] = new_uc_token
            try:
                short_delay()
                resp3 = isolated_session.get(url3, headers=headers3, timeout=15)
                try:
                    res3 = resp3.json()
                except Exception:
                    res3 = {}
                if not res3:
                    print(f"[-] 请求3返回空，重试...")
                    continue
                ticket2 = (res3.get("data") or {}).get("ticket")
                if not ticket2:
                    print(f"[-] 获取微应用ticket失败: {res3}")
                    continue
            except Exception as e:
                print(f"[-] 请求3异常: {e}")
                continue

            # 4. 获取微应用 pro_token
            url4 = "https://www.htx.com.ph/-/x/pro/v1/users/login"
            headers4 = {
                "content-type": "application/json;charset=UTF-8",
                "accept-language": "zh-CN",
                "source": "web",
                "hb-uc-token": quote(new_uc_token),
                "vtoken": self.vtoken,
                "origin": "https://www.htx.com.ph",
                "x-requested-with": "pro.huobi",
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "User-Agent": self.device.get('browser_ua', '')
            }
            data4 = {"ticket": ticket2}
            try:
                short_delay()
                resp4 = isolated_session.post(
                    url4, headers=headers4, json=data4, timeout=15)
                try:
                    res4 = resp4.json()
                except Exception:
                    res4 = {}
                if not res4:
                    print(f"[-] 请求4返回空，重试...")
                    continue
                if res4.get("status") == "ok":
                    new_pro_token = (res4.get("data") or {}).get("token")
                else:
                    print(f"[-] 微应用登录失败: {res4}")
                    continue
            except Exception as e:
                print(f"[-] 请求4异常: {e}")
                continue

            # 5. 加入转盘活动
            url5 = "https://www.bbagl.com/-/x/activity-center/hbg/v1/activity/turntable/join"
            ua_str = self.device.get('browser_ua', '')
            headers5 = {
                "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Android WebView";v="128"',
                "accept-language": "zh-CN",
                "sec-ch-ua-mobile": "?1",
                "content-type": "application/json;charset=UTF-8",
                "vtoken": self.vtoken,
                "hb-pro-token": new_pro_token,
                "hb-uc-token": new_uc_token,
                "sec-ch-ua-platform": '"Android"',
                "origin": "https://www.bbagl.com",
                "x-requested-with": "pro.huobi",
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "referer": f"https://www.bbagl.com/microapps/zh-cn/double-invite-retail/round-about?activityId={activity_id}",
                "User-Agent": ua_str
            }
            data5 = {"activityId": activity_id}
            try:
                short_delay()
                resp5 = isolated_session.post(
                    url5, headers=headers5, json=data5, timeout=15)
                try:
                    res5 = resp5.json()
                except Exception:
                    res5 = {}
                print(
                    f"[DEBUG] turntable/join: {json.dumps(res5, ensure_ascii=False)}")
                if res5 and str(res5.get("code")) != "200":
                    msg = res5.get("message", "")
                    if "不满足加入条件" in msg:
                        print(f"[-] 加入转盘失败: {msg}")
                        return False
                    print(f"[-] 加入转盘失败: {msg}，重试...")
                    continue
            except Exception as e:
                print(f"[-] 请求5异常: {e}")
                continue

            # 6. 获取用户信息 (GET)
            url6 = f"https://www.bbagl.com/-/x/activity-center/hbg/v1/activity/turntable/userInfo?activityId={activity_id}"
            try:
                short_delay()
                resp6 = isolated_session.get(url6, headers=headers5, timeout=15)
                try:
                    res6 = resp6.json()
                except Exception:
                    res6 = {}
                print(
                    f"[DEBUG] turntable/userInfo: {json.dumps(res6, ensure_ascii=False)}")
                if res6 and str(res6.get("code")) != "200":
                    print(f"[-] 获取用户信息失败: {res6.get('message')}，重试...")
                    continue
            except Exception as e:
                print(f"[-] 请求6异常: {e}，重试...")
                continue

            # 7. 获取任务 (GET)
            url7 = f"https://www.bbagl.com/-/x/activity-center/hbg/v1/activity/turntable/tasks?activityId={activity_id}"
            try:
                short_delay()
                resp7 = isolated_session.get(url7, headers=headers5, timeout=15)
                try:
                    res7 = resp7.json()
                except Exception:
                    res7 = {}
                if res7 and str(res7.get("code")) != "200":
                    print(f"[-] 获取任务失败: {res7.get('message')}，重试...")
                    continue
            except Exception as e:
                print(f"[-] 请求7异常: {e}，重试...")
                continue

            # 8. 查询抽奖次数
            url8 = f"https://www.htx.com.ph/-/x/activity-center/hbg/v1/activity/turntable/count?activityId={activity_id}"
            headers8 = {
                "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Android WebView";v="128"',
                "accept-language": "zh-CN",
                "sec-ch-ua-mobile": "?1",
                "content-type": "application/json;charset=UTF-8",
                "vtoken": self.vtoken,
                "accept": "application/json, text/plain, */*",
                "hb-pro-token": new_pro_token,
                "hb-uc-token": new_uc_token,
                "sec-ch-ua-platform": '"Android"',
                "x-requested-with": "pro.huobi",
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "referer": f"https://www.bbagl.com/microapps/zh-cn/double-invite-retail/round-about?activityId={activity_id}",
                "User-Agent": ua_str
            }
            try:
                short_delay()
                resp8 = isolated_session.get(url8, headers=headers8, timeout=15)
                try:
                    res8 = resp8.json()
                except Exception:
                    res8 = {}
                if not res8:
                    print(f"[-] 请求8返回空，重试...")
                    continue
                print(
                    f"[DEBUG] turntable/count: {json.dumps(res8, ensure_ascii=False)}")
                if str(res8.get("code")) != "200":
                    print(f"[-] 查询抽奖次数失败: {res8.get('message')}，返回")
                    return False
                remain = (res8.get("data") or {}).get("count", "?")
                print(f"[*] 剩余抽奖次数: {remain}")
            except Exception as e:
                print(f"[-] 请求8异常: {e}")
                continue

            # 9. 抽奖
            url9 = "https://www.htx.com.ph/-/x/activity-center/hbg/v1/activity/draw/award"
            headers9 = {
                "vtoken": self.vtoken,
                "hb-pro-token": new_pro_token,
                "accept-language": "zh-CN",
                "hb-uc-token": new_uc_token,
                "content-type": "application/json;charset=UTF-8",
                "origin": "https://www.htx.com.ph",
                "x-requested-with": "pro.huobi",
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "referer": f"https://www.aglmt.com/microapps/zh-cn/double-invite-retail/round-about?activityId={activity_id}",
                "User-Agent": self.device.get('browser_ua', '')
            }
            old_vtoken = str(uuid.uuid4()).replace('-', '')
            data9 = {
                "activityId": activity_id,
                "count": 1,
                "vtoken": self.vtoken,
                "oldVtoken": old_vtoken
            }
            try:
                short_delay()
                resp9 = isolated_session.post(
                    url9, headers=headers9, json=data9, timeout=15)
                try:
                    res9 = resp9.json()
                except Exception:
                    res9 = {}
                print(
                    f"[DEBUG] draw/award 原始响应: {json.dumps(res9, ensure_ascii=False)}")
                if str(res9.get("code")) != "200":
                    msg = res9.get("message", "")
                    print(f"[-] 抽奖失败: {msg}")
                    if "抽奖次数不足" in msg:
                        print("[*] 抽奖次数已用完，结束抽奖")
                        break
                    continue

                data_list = res9.get("data") or []
                if data_list and len(data_list) > 0:
                    award_item = data_list[0]
                    props_map = award_item.get("propertiesMap") or {}
                    value = str(props_map.get("value") or "").strip()
                    if value:
                        reward_str_final = value
                    else:
                        count_val = str(award_item.get("count") or "").strip()
                        desc_val = str(award_item.get("desc") or "").strip()
                        reward_str_final = f"{count_val}{desc_val}".strip()
                        if not reward_str_final:
                            award_id = str(award_item.get("awardId") or "").strip()
                            reward_str_final = f"awardId={award_id}"
                else:
                    reward_str_final = "(未解析到奖励详情)"

                print(f"[+] 抽奖成功！获得奖励: {reward_str_final}")
                draw_success_flag = True

                if email:
                    with airdrop_success_lock:
                        if email not in airdrop_success_accounts:
                            airdrop_success_accounts.append(email)
                break

            except Exception as e:
                print(f"[-] 请求9异常: {e}")
                continue

        if not draw_success_flag:
            airdrop_fail_count += 1
            print(f"[*] 抽奖失败次数: {airdrop_fail_count}/{max_airdrop_failures}")
            if airdrop_fail_count >= max_airdrop_failures:
                print(f"[!] 抽奖连续失败 {max_airdrop_failures} 次，停止后续流程")
                try:
                    import huobi_batch_v2 as hb
                    if hasattr(hb, 'stop_event') and hb.stop_event:
                        hb.stop_event.set()
                except:
                    pass
            return False

        airdrop_fail_count = 0
        return True

    def do_sign_in_and_draw(self, enable_delete_htx_emails=True, enable_airdrop=True):
        """执行签到并领取奖励（优化后）
        :param enable_delete_htx_emails: 是否在绑定GA后删除HTX邮件
        :param enable_airdrop: 是否执行空投抽奖
        """
        global airdrop_fail_count
        global max_airdrop_failures
        print("\n" + "-"*40)
        print("开始执行签到和抽奖流程")
        print("-"*40)

        if not self.hb_pro_token:
            print("[*] 注册成功，正在获取业务令牌 (pro_token)...")
            if not self.login():
                print("[!] 登录失败，无法继续")
                return False

        short_delay()

        # 1. 执行空投抽奖 (新增)
        draw_success = True  # 默认成功，以便即使跳过也能继续执行后续流程
        if enable_airdrop:
            print("\n[*] 正在执行大转盘抽奖...")
            # 先获取详情 (可选，用于调试)
            # self.airdrop_detail()

            print("[*] 详情获取后等待 5 秒...")
            time.sleep(4)

            # 获取邮箱地址
            email = None
            if hasattr(self, 'register_email_info'):
                email = self.register_email_info.get("email")

            # 执行抽奖
            draw_success = self.turntable_draw(email=email)

            # 检查是否达到最大失败次数
            if airdrop_fail_count >= max_airdrop_failures:
                print(f"[!] 空投抽奖连续失败 {max_airdrop_failures} 次，停止后续流程")
                return False
        else:
            print("\n[*] 跳过大转盘抽奖")

        short_delay()

        # 2. 执行原有签到任务
        # 注意：如果抽奖使用了隔离Session，我们需要确保这里仍然使用主Session进行签到
        print("\n[*] 获取任务列表...")
        novice_data = self.get_novice_tasks()

        drawable_tasks = []
        groups = novice_data.get('newBeginnerTaskGroups', [])
        for group in groups:
            tasks = group.get('tasks', [])
            for task in tasks:
                status = task.get('status')
                user_task_id = task.get('userTaskId')
                name = task.get('showTitle', '未知任务')

                if status == 5 and user_task_id:
                    drawable_tasks.append({'id': user_task_id, 'name': name})
                    print(f"  [发现可领取任务] {name} (ID: {user_task_id})")

        if drawable_tasks:
            print(f"\n[*] 共发现 {len(drawable_tasks)} 个可领取的任务")
            for task in drawable_tasks:
                print(f"\n[*] 正在领取: {task['name']}")
                self.draw_task_prize(task['id'])
                short_delay()  # 将medium_delay改为short_delay
        else:
            print("[*] 没有可领取的任务")

      #  print("\n[*] 检查签到状态...")
       # self.get_check_in_tasks()
        # 获取邀请码 (可配置)
        if getattr(self, 'enable_get_invite_code', True):
            print("\n[*] 获取邀请码...")
            self.get_invite_code()
        else:
            print("\n[*] 跳过获取邀请码")

        # 打印会话统计
        session_duration = time.time() - self.session_start_time
        print(
            f"\n[统计] 会话时长: {session_duration:.1f}秒, 请求数: {self.request_count}")

        # 执行GA绑定流程 (无论抽奖成功与否都执行)
        # 从 self.register_email_info 获取邮箱凭证
        if hasattr(self, 'register_email_info'):
            self.bind_ga_process(
                email=self.register_email_info.get("email"),
                password=self.register_email_info.get("password"),
                client_id=self.register_email_info.get("client_id"),
                refresh_token=self.register_email_info.get("refresh_token"),
                email_type=self.register_email_info.get("email_type"),
                enable_delete_htx_emails=enable_delete_htx_emails
            )
        else:
            print("[!] 未找到注册邮箱凭证，跳过 GA 绑定流程")
            # 也可以选择尝试执行，但不带凭证 (虽然这会导致获取验证码失败)
            # self.bind_ga_process()

        print("\n[+] 签到和抽奖流程完成!")
        return True


# ==================== 辅助函数 ====================

def log_result(file_path, content):
    """记录结果到文件"""
    with file_lock:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(content + "\n")


def save_account_json(email, password, uid, uc_token, register_time, device_config, client_id=None, refresh_token=None, invite_code=None, hb_pro_token=None, hb_uc_token=None, ga_key=None, hb_uc_ua=None, x_b3_traceid=None, vtoken=None):
    """保存账号数据为JSON格式"""
    import os

    # 创建账号数据目录
    accounts_dir = "accounts_data"
    if not os.path.exists(accounts_dir):
        os.makedirs(accounts_dir)

    # 生成文件名
    safe_email = email.replace('@', '_').replace('.', '_')
    json_file = os.path.join(accounts_dir, f"{safe_email}.json")

    # 构建账号数据
    account_data = {
        "email": email,
        "password": password,
        "uid": uid,
        "uc_token": uc_token,
        "register_time": register_time,
        "device_config": device_config,
        "client_id": client_id,
        "refresh_token": refresh_token,
        "invite_code": invite_code,
        "hb_pro_token": hb_pro_token,
        "hb_uc_token": hb_uc_token,
        "ga_key": ga_key,
        "hb-uc-ua": hb_uc_ua,
        "x-b3-traceid": x_b3_traceid,
        "vtoken": vtoken,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    # 写入JSON文件
    with file_lock:
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(account_data, f, ensure_ascii=False, indent=2)

    print(f"[+] 账号数据已保存到 JSON 文件: {json_file}")


def load_account_json(email=None, json_file=None):
    """从JSON文件加载账号数据"""
    import os

    # 创建账号数据目录
    accounts_dir = "accounts_data"
    if not os.path.exists(accounts_dir):
        print(f"[!] 账号数据目录不存在: {accounts_dir}")
        return None

    # 确定JSON文件路径
    if json_file:
        if not os.path.exists(json_file):
            print(f"[!] JSON文件不存在: {json_file}")
            return None
        target_file = json_file
    elif email:
        safe_email = email.replace('@', '_').replace('.', '_')
        target_file = os.path.join(accounts_dir, f"{safe_email}.json")
        if not os.path.exists(target_file):
            print(f"[!] 账号JSON文件不存在: {target_file}")
            return None
    else:
        print("[!] 必须提供邮箱地址或JSON文件路径")
        return None

    # 读取JSON文件
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            account_data = json.load(f)
        print(f"[+] 成功加载账号数据: {target_file}")
        return account_data
    except Exception as e:
        print(f"[!] 加载账号数据异常: {e}")
        return None


def list_accounts():
    """列出所有已保存的账号"""
    import os

    accounts_dir = "accounts_data"
    if not os.path.exists(accounts_dir):
        print(f"[!] 账号数据目录不存在: {accounts_dir}")
        return []

    accounts = []
    for filename in os.listdir(accounts_dir):
        if filename.endswith('.json'):
            json_file = os.path.join(accounts_dir, filename)
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    account_data = json.load(f)
                accounts.append({
                    "email": account_data.get("email"),
                    "uid": account_data.get("uid"),
                    "file": json_file,
                    "created_at": account_data.get("created_at")
                })
            except:
                pass

    print(f"[*] 共找到 {len(accounts)} 个已保存的账号:")
    for i, acc in enumerate(accounts, 1):
        print(
            f"[{i}] 邮箱: {acc['email']}, UID: {acc['uid']}, 创建时间: {acc['created_at']}")

    return accounts


def restore_client_from_account_data(account_data, proxies=None):
    """从账号数据恢复HuobiClient实例"""
    try:
        # 提取设备配置
        device_config = account_data.get("device_config", {})
        if not device_config:
            print("[!] 账号数据中缺少设备配置")
            return None

        # 创建新的HuobiClient实例
        client = HuobiClient(device_config, proxies)

        # 恢复认证信息
        client.hb_uc_token = account_data.get("hb_uc_token")
        client.hb_pro_token = account_data.get("hb_pro_token")
        client.uid = account_data.get("uid")
        client.invite_code = account_data.get("invite_code")

        # 恢复设备标识
        client.vtoken = account_data.get("vtoken") or device_config.get(
            'android_id') or device_config.get('fingerprint', '')
        client.fingerprint = device_config.get('fingerprint', '')

        # 恢复其他动态参数
        client.trace_id = generate_trace_id()
        client.ctx_id = generate_ctx_id()
        client.vulcan_uuid = generate_vulcan_uuid()
        client.urid = generate_urid()

        # 恢复 hb_uc_ua
        if account_data.get("hb-uc-ua"):
            client.hb_uc_ua = account_data.get("hb-uc-ua")

        print(f"[+] 成功恢复HuobiClient实例")
        print(f"  邮箱: {account_data.get('email')}")
        print(f"  UID: {client.uid}")
        print(f"  设备指纹: {client.fingerprint[:20]}...")

        return client
    except Exception as e:
        print(f"[!] 恢复HuobiClient实例异常: {e}")
        import traceback
        traceback.print_exc()
        return None


def sign_in_from_json(email=None, json_file=None, proxies=None):
    """从JSON文件加载数据进行签到"""
    print(f"\n{'='*60}")
    print("[*] 开始执行单独签到流程")
    print(f"{'='*60}")

    try:
        # 加载账号数据
        account_data = load_account_json(email, json_file)
        if not account_data:
            print("[!] 加载账号数据失败，无法执行签到")
            return False

        # 恢复HuobiClient实例
        client = restore_client_from_account_data(account_data, proxies)
        if not client:
            print("[!] 恢复HuobiClient实例失败，无法执行签到")
            return False

        # 执行签到和抽奖
        print(f"\n[*] 开始执行签到和抽奖...")
        success = client.do_sign_in_and_draw()

        if success:
            print(f"\n[+] 单独签到流程执行成功！")
            print(f"  账号: {account_data.get('email')}")
            print(f"  UID: {client.uid}")
        else:
            print(f"\n[-] 单独签到流程执行失败")

        return success
    except Exception as e:
        print(f"[!] 单独签到流程异常: {e}")
        import traceback
        traceback.print_exc()
        return False


def batch_sign_in():
    """批量执行所有已保存账号的签到"""
    print(f"\n{'='*60}")
    print("[*] 开始执行批量签到流程")
    print(f"{'='*60}")

    # 列出所有账号
    accounts = list_accounts()
    if not accounts:
        print("[!] 没有找到已保存的账号")
        return

    success_count = 0
    failure_count = 0

    for i, acc in enumerate(accounts, 1):
        print(f"\n{'='*40}")
        print(f"[*] 处理账号 {i}/{len(accounts)}")
        print(f"  邮箱: {acc['email']}")
        print(f"  文件: {acc['file']}")
        print(f"{'='*40}")

        # 执行签到
        success = sign_in_from_json(json_file=acc['file'])
        if success:
            success_count += 1
        else:
            failure_count += 1

        # 添加延迟，避免请求过于频繁
        if i < len(accounts):
            print(f"[*] 等待 3-5 秒后处理下一个账号...")
            time.sleep(random.uniform(3, 5))

    print(f"\n{'='*60}")
    print("[*] 批量签到流程完成")
    print(f"{'='*60}")
    print(f"[*] 成功: {success_count} 个账号")
    print(f"[*] 失败: {failure_count} 个账号")
    print(f"[*] 总计: {len(accounts)} 个账号")


def remove_processed_emails():
    """从输入文件中删除已处理的邮箱"""
    if not processed_emails:
        return
    with file_lock:
        try:
            with open(INPUT_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = [l for l in lines if (
                l.split("----")[0].strip() if "----" in l else "") not in processed_emails]
            with open(INPUT_FILE, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            print(f"\n[*] 已清理文件，剔除 {len(processed_emails)} 个已处理邮箱。")
        except Exception as e:
            print(f"\n[!] 清理文件失败: {e}")


def should_stop():
    """判断是否应该停止注册"""
    if not ENABLE_LIMIT:
        return False
    if MAX_REGISTER_COUNT <= 0:
        return False
    with success_lock:
        return success_count >= MAX_REGISTER_COUNT


# ==================== 注册工作线程 ====================

def register_worker_with_stop(email_data, stop_event, args, enable_sign_in=True, enable_get_invite_code=True, enable_delete_htx_emails=True, enable_airdrop=True):
    """带停止检查的注册工作线程"""
    global success_count

    # 静默检查是否应该停止
    if should_stop() or stop_event.is_set():
        return

    try:
        parts = email_data.strip().split("----")
        invite_code = None

        if len(parts) >= 4:
            # 新格式: 账号----密码----client_id----oauth2_refresh_token----[invite_code]
            email, email_pwd, client_id, refresh_token = parts[0], parts[1], parts[2], parts[3]
            if len(parts) >= 5:
                invite_code = parts[4]
        elif len(parts) == 2:
            # 旧格式: 账号----密码
            email, email_pwd = parts[0], parts[1]
            client_id = None
            refresh_token = None
        else:
            raise ValueError("格式错误")
    except Exception as e:
        print(f"[!] 邮箱格式错误: {email_data}")
        print(f"[DEBUG] 错误: {e}")
        return

    password = email_pwd
    retry_count = 0

    while retry_count < MAX_RETRY_PER_ACCOUNT:
        if should_stop() or stop_event.is_set():
            print(f"[*] 收到停止信号，停止处理账号: {email}")
            return

        # 使用增强版设备配置
        device = get_enhanced_device_config()

        proxies = None
        if not args.no_proxy:
            proxy_mgr = ProxyManager(PROXY_API_URL)
            proxies = proxy_mgr.get_proxy()

        client = HuobiClient(device, proxies=proxies)
        # 设置获取邀请码标志
        client.enable_get_invite_code = enable_get_invite_code

        print(f"\n{'='*60}")
        print(f"[*] 正在处理账号: {email} (尝试次数: {retry_count + 1})")
        print(
            f"[*] 模拟设备: {device['brand']} {device['model']} (Android {device['sys_ver']})"
        )
        print(f"[*] 代理: {proxies['http'] if proxies else '本地IP'}")
        print(f"[*] 设备指纹: {client.fingerprint}")
        print(f"[*] TLS伪装: {'已启用 (curl_cffi)' if USE_CURL_CFFI else '未启用'}")
        print(f"{'='*60}")

        try:
            # 0. 预热请求
            client.warmup()

            # 1. 预检
            print("[1] 正在执行预检 (preliminary_check)...")
            preliminary_result = client.preliminary_check(email)

            if not preliminary_result.get("success"):
                message = str(preliminary_result.get("message", "未知错误"))
                if "已注册" in message:
                    print(f"[-] 预检失败：邮箱已注册 - {email}")
                    processed_emails.add(email)
                    remove_processed_emails()
                    return
                elif "封禁" in message or "限制" in message or "block" in message.lower():
                    print(f"[-] 预检失败：邮箱被封禁 - {email}")
                    processed_emails.add(email)
                    remove_processed_emails()
                    return
                else:
                    print(f"[-] 预检失败：{message}")
                    processed_emails.add(email)
                    remove_processed_emails()
                    return

            print("[+] 预检成功：邮箱可用")

            # 2. 获取风控数据
            print("[2] 正在获取风控数据 (get_risk_control)...")
            risk_data = client.get_risk_control(email)
            if not risk_data:
                print("[!] 风控接口返回空，正在切换代理重试...")
                retry_count += 1
                long_delay()
                continue

            print(
                f"[RAW RESPONSE] {json.dumps(risk_data, ensure_ascii=False)[:200]}...")

            # 提取极验ID逻辑优化
            captcha_id = None
            itemsv3 = risk_data.get("data", {}).get("itemsv3", [])

            # 优先尝试从 itemsv3[1] 获取 (根据用户反馈)
            if len(itemsv3) > 1:
                item = itemsv3[1]
                if item.get("type") == 3:
                    captcha_id = item.get("properties", {}).get("captcha_id")
                    print(f"[DEBUG] 从 itemsv3[1] 提取到 captcha_id: {captcha_id}")

            # 如果没获取到，尝试遍历 itemsv3
            if not captcha_id:
                for item in itemsv3:
                    if item.get("type") == 3:
                        captcha_id = item.get(
                            "properties", {}).get("captcha_id")
                        if captcha_id:
                            print(
                                f"[DEBUG] 从 itemsv3 遍历提取到 captcha_id: {captcha_id}")
                            break

            # 如果还没获取到，尝试遍历 items (旧逻辑)
            if not captcha_id:
                items = risk_data.get("data", {}).get("items", [])
                for item in items:
                    if item.get("type") == 3:
                        captcha_id = item.get(
                            "properties", {}).get("captcha_id")
                        if captcha_id:
                            print(
                                f"[DEBUG] 从 items 遍历提取到 captcha_id: {captcha_id}")
                            break

            if not captcha_id:
                print("[-] 无法从响应中提取极验ID")
                return

            print(f"[+] 提取到极验ID: {captcha_id}")

            # 3. 破解极验
            print(f"[3] 正在破解极验 (captcha_id: {captcha_id})...")
            solution = solve_geetest_v4(captcha_id, proxy=proxies)
            if not solution:
                print("[-] 极验破解失败，正在切换代理重试...")
                retry_count += 1
                long_delay()
                continue
            print(f"[+] 极验破解成功")
            solution["captcha_id"] = captcha_id

            # 4. 发送邮件
            print("[4] 正在发送邮件验证码 (send_email_code)...")
            send_res = client.send_email_code(email, solution)

            if not send_res:
                print("[!] 发送邮件接口返回空，判定为代理风控，正在切换代理重试...")
                retry_count += 1
                long_delay()
                continue

            print(f"[RAW RESPONSE] {json.dumps(send_res, ensure_ascii=False)}")
            if not send_res.get("success"):
                msg = str(send_res.get("message"))
                if "已注册" in msg:
                    print(f"[-] 邮箱已注册，从列表中删除: {email}")
                    processed_emails.add(email)
                    remove_processed_emails()
                    return
                print(f"[-] 发送失败: {msg}，正在切换代理重试...")
                retry_count += 1
                long_delay()
                continue

            # 5. 获取验证码（模拟人类等待时间）
            print("[5] 正在从邮箱获取验证码...")
            human_typing_delay()  # 模拟人类查看邮件的时间
            auth_code = get_email_auth_code(
                email, email_pwd, client_id=client_id, refresh_token=refresh_token, email_type=getattr(args, 'email_type', 'self'))
            if not auth_code:
                print("[-] 获取验证码超时")
                return

            # 6. 验证验证码
            print("[6] 正在验证验证码 (verify_auth_code)...")
            verify_res = client.verify_auth_code(email, auth_code)
            if not verify_res:
                print("[!] 验证接口返回空，正在切换代理重试...")
                retry_count += 1
                long_delay()
                continue
            if not verify_res.get("success"):
                print(f"[-] 验证失败: {verify_res}")
                # 如果验证码不正确，延迟2秒后重新尝试获取验证码
                if verify_res.get("code") == 10023 or "验证码不正确" in verify_res.get("message", ""):
                    print("[*] 验证码不正确，延迟2秒后重新尝试获取验证码...")
                    time.sleep(2)
                    # 重新获取验证码
                    auth_code = get_email_auth_code(
                        email, email_pwd, client_id=client_id, refresh_token=refresh_token, email_type=getattr(args, 'email_type', 'self'))
                    if not auth_code:
                        print("[-] 重新获取验证码超时")
                        return
                    # 再次验证验证码
                    verify_res = client.verify_auth_code(email, auth_code)
                    if not verify_res or not verify_res.get("success"):
                        print(f"[-] 再次验证失败: {verify_res}")
                        return

            real_token = verify_res.get("data", {}).get("auth_token")

            # 7. 提交注册
            current_invite_code = invite_code if invite_code else INVITE_CODE
            print(f"[7] 正在提交注册 (register)... 邀请码: {current_invite_code}")
            res = client.register(email, password, auth_code, real_token,
                                  client_id=client_id,
                                  refresh_token=refresh_token,
                                  email_type=getattr(
                                      args, 'email_type', 'self'),
                                  invite_code=invite_code)
            if not res:
                print("[!] 注册提交返回空，正在切换代理重试...")
                retry_count += 1
                long_delay()
                continue
            print(f"[RAW RESPONSE] {json.dumps(res, ensure_ascii=False)}")

            if res.get("success"):
                with success_lock:
                    if ENABLE_LIMIT and MAX_REGISTER_COUNT > 0 and success_count >= MAX_REGISTER_COUNT:
                        return

                    success_count += 1
                    current_count = success_count

                print(
                    f"[★★★] 账号 {email} 注册成功！(当前成功: {current_count}/{MAX_REGISTER_COUNT if ENABLE_LIMIT and MAX_REGISTER_COUNT > 0 else '∞'})")

                # 8. 注册成功后执行签到和抽奖
                if enable_sign_in:
                    print("\n[8] 注册成功，开始执行签到和抽奖...")
                    long_delay()
                    signin_success = client.do_sign_in_and_draw(
                        enable_delete_htx_emails=enable_delete_htx_emails,
                        enable_airdrop=enable_airdrop)

                    # 检查签到和抽奖是否成功
                    if not signin_success:
                        # 检查是否是因为空投抽奖失败次数过多
                        global airdrop_fail_count
                        global max_airdrop_failures
                        if airdrop_fail_count >= max_airdrop_failures:
                            print(
                                f"[!] 空投抽奖连续失败 {max_airdrop_failures} 次，停止注册流程")
                            # 设置全局停止标志
                            stop_event.set()
                            processed_emails.add(email)
                            return
                else:
                    # 即使不启用签到抽奖，也执行GA绑定流程
                    print("\n[8] 注册成功，执行GA绑定流程...")
                    long_delay()
                    if hasattr(client, 'register_email_info'):
                        client.bind_ga_process(
                            email=client.register_email_info.get("email"),
                            password=client.register_email_info.get(
                                "password"),
                            client_id=client.register_email_info.get(
                                "client_id"),
                            refresh_token=client.register_email_info.get(
                                "refresh_token"),
                            email_type=client.register_email_info.get(
                                "email_type"),
                            enable_delete_htx_emails=enable_delete_htx_emails
                        )
                    else:
                        print("[!] 未找到注册邮箱凭证，跳过 GA 绑定流程")

                processed_emails.add(email)

                register_data = res.get("data", {})
                uid = register_data.get("uid")
                uc_token = register_data.get("uc_token")
                register_time = register_data.get(
                    "register_time", int(time.time() * 1000))
                device_config_json = json.dumps(device, ensure_ascii=False)
                # 确保获取真实的邀请码，而不是依赖注册响应
                if client.invite_code and client.invite_code != "未知":
                    邀请码 = client.invite_code
                else:
                    邀请码 = register_data.get("invite_code", "NONE")

                # 获取 ga_key (如果 GA 流程执行了的话)
                ga_key = getattr(client, 'ga_key', 'NONE')

                # 根据账号类型使用不同的保存格式
                if client_id and refresh_token:
                    # 微软邮箱格式: 账号----密码----微软token----微软令牌----邀请码----谷歌key
                    account_line2 = f"{email}|{password}|{client_id}|{refresh_token}|{邀请码}|{ga_key}"
                    account_line = f"{email}|{password}|{client_id}|{refresh_token}|{邀请码}|{ga_key}"

                else:
                    # 自建邮箱格式: 账号----密码----uid----gakey----|----vtoken----vtoken2----fingerprint----hb_uc_ua----hb_uc_token
                    account_line2 = f"{email}----{password}----{uid}----{ga_key}----|----{client.vtoken}----{client.vtoken2}----{client.fingerprint}----{client.hb_uc_ua}----{client.hb_uc_token or 'NONE'}"
                    account_line = f"{email}----{password}----{uid}----{ga_key}----|----{client.vtoken}----{client.vtoken2}----{client.fingerprint}----{client.hb_uc_ua}----{client.hb_uc_token or 'NONE'}"
                log_result(SUCCESS_FILE_SIMPLE, account_line2)
                log_result(SUCCESS_FILE, account_line)

                # 保存为JSON格式
                save_account_json(
                    email=email,
                    password=password,
                    uid=uid,
                    uc_token=uc_token,
                    register_time=register_time,
                    device_config=device,
                    client_id=client_id,
                    refresh_token=refresh_token,
                    invite_code=邀请码,
                    hb_pro_token=client.hb_pro_token,
                    hb_uc_token=client.hb_uc_token,
                    ga_key=ga_key,
                    hb_uc_ua=client.hb_uc_ua,
                    x_b3_traceid=client.trace_id,
                    vtoken=client.vtoken
                )

                # 检查该账号是否空投抽奖成功，如果成功则保存详细信息
                global airdrop_success_accounts
                global airdrop_success_lock
                with airdrop_success_lock:
                    if email in airdrop_success_accounts:
                        # 移除旧的只包含邮箱的记录
                        airdrop_success_accounts.remove(email)
                        # 添加完整的账号信息
                        account_info = {
                            "email": email,
                            "password": password,
                            "client_id": client_id,
                            "refresh_token": refresh_token,
                            "invite_code": 邀请码,
                            "ga_key": ga_key
                        }
                        airdrop_success_accounts.append(account_info)

                return
            else:
                print(f"[-] 注册失败: {res.get('message')}")
                return

        except Exception as e:
            print(f"[!] 运行异常: {e}")
            import traceback
            traceback.print_exc()
            retry_count += 1
            long_delay()

    print(f"[-] 账号 {email} 在尝试 {MAX_RETRY_PER_ACCOUNT} 次更换代理后依然失败。")


# ==================== 主函数 ====================

def main():
    global stop_event
    global MAX_REGISTER_COUNT
    stop_event = threading.Event()

    parser = argparse.ArgumentParser(
        description='火币（HTX）批量注册+签到+抽奖脚本 (增强反检测版 V3)')
    parser.add_argument('--emails', type=str, help='指定邮箱地址')
    parser.add_argument('--email-file', type=str, help='指定邮箱文件路径')
    parser.add_argument('--password', type=str, help='指定密码')
    parser.add_argument('--count', type=int,
                        default=MAX_REGISTER_COUNT, help='最大注册数量')
    parser.add_argument('--no-proxy', action='store_true', help='不使用代理')
    parser.add_argument('--no-sign-in', action='store_true', help='注册后不执行签到抽奖')
    # 新增签到相关参数
    parser.add_argument('--sign-in', action='store_true', help='执行单独签到')
    parser.add_argument('--sign-in-email', type=str, help='指定要签到的邮箱')
    parser.add_argument('--sign-in-file', type=str, help='指定签到的JSON文件')
    parser.add_argument('--batch-sign-in',
                        action='store_true', help='批量执行所有账号的签到')
    parser.add_argument('--list-accounts',
                        action='store_true', help='列出所有已保存的账号')
    args = parser.parse_args()

    def signal_handler(signum, frame):
        print(f"\n{'='*60}")
        print(f"[!] 收到停止信号 (信号: {signum})")
        print(f"[*] 正在停止所有线程...")
        print(f"{'='*60}")

        stop_event.set()
        time.sleep(2)
        remove_processed_emails()

        print(f"\n{'='*60}")
        print(f"[*] 中断前统计")
        print(f"{'='*60}")
        print(f"[*] 成功注册: {success_count} 个账号")
        print(f"[*] 处理账号: {len(processed_emails)} 个账号")
        print(f"{'='*60}")

        exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 处理签到相关命令
    if args.list_accounts:
        list_accounts()
        return

    if args.batch_sign_in:
        batch_sign_in()
        return

    if args.sign_in:
        sign_in_from_json(email=args.sign_in_email,
                          json_file=args.sign_in_file)
        return

    try:
        if args.emails and args.password:
            email_list = [f"{args.emails}----{args.password}"]
        elif args.email_file:
            with open(args.email_file, "r", encoding="utf-8") as f:
                email_list = [l.strip() for l in f if l.strip()]
        else:
            with open(INPUT_FILE, "r", encoding="utf-8") as f:
                email_list = [l.strip() for l in f if l.strip()]
    except FileNotFoundError:
        print(f"[!] 文件未找到: {INPUT_FILE}")
        return

    if args.count:
        MAX_REGISTER_COUNT = args.count

    email_list = email_list[START_INDEX:]

    print(f"\n{'='*60}")
    print(f"火币（HTX）批量注册+签到+抽奖脚本 (增强反检测版 V3)")
    print(f"{'='*60}")
    print(f"[*] 待处理账号数: {len(email_list)}")
    print(f"[*] 并发线程数: {MAX_WORKERS}")
    print(
        f"[*] 注册数量限制: {MAX_REGISTER_COUNT if ENABLE_LIMIT and MAX_REGISTER_COUNT > 0 else '无限制'}")
    print(f"[*] 使用代理: {'否' if args.no_proxy else '是'}")
    print(f"[*] 注册后签到: {'否' if args.no_sign_in else '是'}")
    print(f"[*] 设备池大小: {len(ENHANCED_DEVICE_POOL)} 种设备")
    print(f"[*] Chrome版本池: {len(CHROME_VERSIONS)} 个版本")
    print(f"{'='*60}\n")

    enable_sign_in = not args.no_sign_in

    # 使用线程池（进程池无法序列化 threading.Lock / threading.Event，会报 pickle 错误）
    print(f"[*] 使用 ThreadPoolExecutor (线程池)")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for email_data in email_list:
            if should_stop():
                break
            future = executor.submit(
                register_worker_with_stop, email_data, stop_event, args, enable_sign_in)
            futures.append(future)

        for future in as_completed(futures):
            if should_stop():
                break
            try:
                future.result()
            except Exception as e:
                print(f"[!] 任务异常: {e}")

    remove_processed_emails()

    print(f"\n{'='*60}")
    print(f"[*] 批量注册完成统计")
    print(f"{'='*60}")
    print(f"[*] 成功注册: {success_count} 个账号")
    print(f"[*] 处理账号: {len(processed_emails)} 个账号")

    # 保存空投抽奖成功的账号
    global airdrop_success_accounts
    if airdrop_success_accounts:
        airdrop_success_file = "airdrop_success_accounts.txt"
        with open(airdrop_success_file, "a", encoding="utf-8") as f:
            for account_info in airdrop_success_accounts:
                # 检查是字典格式还是字符串格式
                if isinstance(account_info, dict):
                    email = account_info.get("email")
                    password = account_info.get("password")
                    client_id = account_info.get("client_id")
                    refresh_token = account_info.get("refresh_token")
                    invite_code = account_info.get("invite_code", "NONE")
                    ga_key = account_info.get("ga_key", "NONE")

                    # 根据是否有client_id和refresh_token决定保存格式
                    if client_id and refresh_token:
                        # 微软账号格式: 邮箱|密码|client_id|refresh_token|邀请码|GA密钥
                        line = f"{email}|{password}|{client_id}|{refresh_token}|{invite_code}|{ga_key}"
                    else:
                        # 普通账号格式: 邮箱|密码|邀请码|GA密钥
                        line = f"{email}|{password}|{invite_code}|{ga_key}"
                    f.write(line + "\n")
                else:
                    # 旧格式: 只保存邮箱
                    f.write(str(account_info) + "\n")
        print(f"[*] 空投抽奖成功: {len(airdrop_success_accounts)} 个账号")
        print(f"[*] 已保存到文件: {airdrop_success_file}")
    else:
        print(f"[*] 空投抽奖成功: 0 个账号")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()

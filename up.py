#!/usr/bin/env python3

import os, re, sys, time, requests
from datetime import datetime, timedelta, timezone
from seleniumbase import SB

# 环境变量 
EMAIL = os.environ.get("EMAIL") or ""            # 邮箱   
PASSWORD = os.environ.get("PASSWORD") or ""      # 密码
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""  # tg通知 bot token
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or ""      # tg通知 chat_id id
PROXY_SOCKS5 = os.environ.get("PROXY_SOCKS5") or ""  # 代理地址

BASE_URL = "https://client.therose.cloud/login"
CART_RENEW_URL = "https://client.therose.cloud/panel?routeName=cart_renew&id=2600"

# 检查必要变量
if not EMAIL or not PASSWORD:
    print("❌ 请设置环境变量 EMAIL 和 PASSWORD")
    sys.exit(1)

# 检查续期是否成功
def check_renewal_success(sb):
    """检查是否出现续期成功的提示"""
    success_selectors = [
        '.alert-success',
        '.alert.alert-success',
        'div[role="alert"].alert-success',
        'div.alert-success',
        'span:contains("successfully purchased")',
        'div:contains("successfully purchased")'
    ]
    
    print("⏳ 等待5秒检查续期结果...")
    time.sleep(5)
    
    for selector in success_selectors:
        try:
            element = sb.find_element(selector, timeout=2)
            if element:
                text = element.text
                print(f"✅ 发现成功提示！选择器: {selector}")
                print(f"📝 提示内容: {text}")
                return True, text
        except:
            continue
    
    # 如果没有找到特定选择器，检查页面源码是否包含成功关键词
    try:
        page_source = sb.get_page_source()
        if "successfully purchased" in page_source.lower():
            print("✅ 页面源码中发现 'successfully purchased' 关键词")
            return True, "服务器已成功续期"
    except:
        pass
    
    return False, "未检测到续期成功提示"

# 发送tg通知（支持文本和图片）
def send_tg(token, chat_id, message, photo_path=None):
    if not token or not chat_id:
        return
    proxies = {"http": PROXY_SOCKS5, "https": PROXY_SOCKS5} if PROXY_SOCKS5 else None
    
    try:
        # 如果提供了图片路径且文件存在，发送图片
        if photo_path and os.path.exists(photo_path):
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(photo_path, 'rb') as photo:
                files = {'photo': photo}
                data = {'chat_id': chat_id, 'caption': message}
                resp = requests.post(url, data=data, files=files, proxies=proxies, timeout=15)
        else:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            resp = requests.post(url, json={"chat_id": chat_id, "text": message}, proxies=proxies, timeout=10)
            
        if resp.status_code == 200:
            print("📨 Telegram 通知已发送")
        else:
            print(f"❌ Telegram 发送失败: {resp.text}")
    except Exception as e:
        print(f"❌ Telegram 发送异常: {e}")

# 登录流程
def login(sb, email, password):
    print("🌐 打开登录页面...")
    sb.open(BASE_URL)
    sb.wait_for_ready_state_complete()
    
    # 显式等待输入框加载完成
    print("⏳ 等待输入框加载...")
    sb.wait_for_element_visible('#login_form_email', timeout=15)
    sb.wait_for_element_visible('#login_form_password', timeout=15)
    sb.sleep(2)

    print("📧 填写邮箱...")
    sb.type('#login_form_email', email, timeout=10)
    
    print("🔑 填写密码...")
    sb.type('#login_form_password', password, timeout=10)
    sb.sleep(1) 

    # 检查输入框是否真的填入了内容，如果未写入则使用 JS 进行兜底赋值
    email_val = sb.get_attribute('#login_form_email', 'value')
    if not email_val:
        print("⚠️ 常规 type 输入未生效，尝试使用 JS 强制写入邮箱和密码...")
        sb.execute_script(f"document.querySelector('#login_form_email').value = '{email}';")
        sb.execute_script(f"document.querySelector('#login_form_password').value = '{password}';")
        sb.execute_script("document.querySelector('#login_form_email').dispatchEvent(new Event('input', { bubbles: true }));")
        sb.execute_script("document.querySelector('#login_form_password').dispatchEvent(new Event('input', { bubbles: true }));")

    print("🛡 处理 Turnstile...")
    sb.sleep(3)
    try:
        sb.uc_gui_click_captcha()
        print("✅ Turnstile 验证已处理")
    except Exception as e:
        print(f"⚠️ uc_gui_click_captcha 执行异常: {e}")

    sb.sleep(2)
    print("🔑 点击登录按钮...")
    sb.uc_click('button:contains("Sign in")')
    
    # 点击后等待 5 秒以让页面状态稳定
    sb.sleep(5)
    
    # 截图并发送到 Telegram
    login_click_img = "login_clicked.png"
    sb.save_screenshot(login_click_img)
    send_tg(TG_BOT_TOKEN, TG_CHAT_ID, "📸 已输入账号密码并点击登录按钮，当前页面状态如下：", photo_path=login_click_img)

    for _ in range(30):
        # 判断是否登录成功
        current_url = sb.get_current_url()
        page_title = sb.get_title() or ""
        print(f"📄 当前 URL: {current_url} | Title: {page_title}")
        if "panel" in current_url:
            print("✅ 登录成功，已跳转到 Dashboard")
            return True, current_url
        time.sleep(1)

    print(f"❌ 登录失败，当前 URL: {sb.get_current_url()}")
    sb.save_screenshot("login_faild.png")
    return False, sb.get_current_url()

# 解析时间字符串并生成 Cron 表达式与续期判定
def handle_renew_time_and_cron(date_text):
    # 提取起始时间部分，例："21.07.2026, 21:50"
    start_str = date_text.split(" - ")[0].strip()
    
    # 解析成 datetime 对象
    start_dt = datetime.strptime(start_str, "%d.%m.%Y, %H:%M").replace(tzinfo=timezone.utc)
    
    # 可续期起始时刻：到期前 30 分钟
    renew_window_start = start_dt - timedelta(minutes=30)
    
    # 计算每 6 小时触发一次对应的四个每天固定时刻 (Cron 分钟与小时)
    minute = renew_window_start.minute
    base_hour = renew_window_start.hour % 6
    hours = [(base_hour + i * 6) % 24 for i in range(4)]
    hours.sort()
    
    hours_str = ",".join(map(str, hours))
    cron_expr = f"{minute} {hours_str} * * *"
    
    # 1. 写入 cron.txt 纯表达式
    with open("cron.txt", "w") as f:
        f.write(cron_expr)
    print(f"📝 固化 Cloudflare Worker Cron 表达式至 cron.txt: {cron_expr}")
    
    # 2. 判断当前时间是否落在可续期时间窗口（到期前30分钟至到期时刻之间）
    now_utc = datetime.now(timezone.utc)
    print(f"🕒 当前 UTC 时间: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⌛ 到期时刻: {start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏳ 允许续期开始时刻: {renew_window_start.strftime('%Y-%m-%d %H:%M:%S')}")
    
    should_renew = renew_window_start <= now_utc <= start_dt
    return should_renew, cron_expr

# 主流程
def main():
    print("🚀 启动浏览器")

    sb_kwargs = {"uc": True, "headless": False}
    if PROXY_SOCKS5:
        print(f"🌐 使用代理启动浏览器: {PROXY_SOCKS5}")
        sb_kwargs["proxy"] = PROXY_SOCKS5

    with SB(**sb_kwargs) as sb:
        success, url = login(sb, EMAIL, PASSWORD)
        
        if not success:
            msg = f"❌ 登录失败"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        print("🌐 直接跳转到续期购物车页面...")
        sb.open(CART_RENEW_URL)
        sb.wait_for_ready_state_complete()
        sb.sleep(2)
        
        # 查找包含续期时间段的元素
        try:
            date_elem = sb.find_element('//*[@id="selected-dates"]', timeout=10)
            date_text = date_elem.text.strip()
            print(f"📅 获取到的续期时间段文本: {date_text}")
        except Exception as e:
            msg = f"❌ 未获取到续期时间段元素 (selected-dates): {e}"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        # 计算 Cron 并判断是否满足续期时间限制
        should_renew, cron_expr = handle_renew_time_and_cron(date_text)
        
        if not should_renew:
            msg = f"ℹ️ 尚未达到续期窗口（需在到期前30分钟内）。已更新 Cron 表达式 [{cron_expr}] 至 cron.txt，跳过本次 Order now。"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return

        # 符合条件，点击 Order now 按钮
        try:
            button = sb.find_element('button:contains("Order now")', timeout=5)
            if button:
                print("🛒 满足时间条件，点击 Order now 按钮...")
                sb.uc_click('button:contains("Order now")')
                print("✅ 已点击 Order now 按钮")
            else:
                msg = "❌ 未找到 Order now 按钮"
                print(msg)
                send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
                return
        except Exception as e:
            msg = f"❌ 点击 Order now 失败: {e}"
            print(msg)
            send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)
            return
        
        # 检查续期是否成功
        print("🔍 检查续期结果...")
        renewal_success, renewal_msg = check_renewal_success(sb)
        
        if renewal_success:
            msg = f"✅ 续期成功！{renewal_msg}\nWorker Cron: {cron_expr}"
            print(msg)
            sb.save_screenshot("renewal_success.png")
        else:
            msg = f"❌ 续期可能失败: {renewal_msg}"
            print(msg)
            sb.save_screenshot("renewal_failed.png")
        
        send_tg(TG_BOT_TOKEN, TG_CHAT_ID, msg)

    print("🏁 脚本执行完毕")

if __name__ == "__main__":
    main()

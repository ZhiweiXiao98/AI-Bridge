import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

def run_detective():
    print("🕵️‍♂️ 侦探脚本启动...")
    
    # 1. 连接已打开的 Chrome
    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9527")
    service = Service()
    try:
        driver = webdriver.Chrome(service=service, options=options)
    except:
        print("❌ 连接失败！请确保你已经通过 launcher.py 启动了 Chrome。")
        return

    print("✅ 已连接浏览器，正在扫描案发现场...")
    print("-" * 30)

    # 2. 寻找隐藏的上传入口
    file_inputs = driver.find_elements(By.XPATH, "//input[@type='file']")
    print(f"🔍 发现了 {len(file_inputs)} 个上传入口：")
    
    for i, inp in enumerate(file_inputs):
        try:
            # 获取 HTML 结构
            html = inp.get_attribute('outerHTML')
            visible = inp.is_displayed()
            print(f"  [{i+1}] 可见性: {'👀 可见' if visible else '🙈 隐藏'}")
            print(f"      HTML: {html[:100]}...") # 只打印前100个字符避免刷屏
        except:
            print(f"  [{i+1}] 无法读取详情")

    print("-" * 30)

    # 3. 寻找“确认”按钮 (通过文字查找，不依赖随机ID)
    print("🔍 正在寻找“确认”按钮...")
    # 尝试多种策略寻找
    confirm_btns = driver.find_elements(By.XPATH, "//button[contains(., '确认')]")
    if not confirm_btns:
        confirm_btns = driver.find_elements(By.XPATH, "//div[contains(text(), '确认')]")
        
    print(f"🔍 发现了 {len(confirm_btns)} 个包含“确认”字的按钮：")
    for i, btn in enumerate(confirm_btns):
        try:
            tag = btn.tag_name
            classes = btn.get_attribute("class")
            print(f"  [{i+1}] 标签: <{tag}>, 类名: {classes}")
            # 尝试高亮它一下，让用户在浏览器里看到
            driver.execute_script("arguments[0].style.border='3px solid red';", btn)
            print("      (已在浏览器中用红框标出，请查看是哪一个)")
        except:
            pass
            
    print("-" * 30)
    print("🕵️‍♂️ 侦探工作结束。请把上面的输出结果复制给我。")

if __name__ == "__main__":
    run_detective()

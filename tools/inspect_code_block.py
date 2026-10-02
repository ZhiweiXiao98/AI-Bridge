# filename: tools/inspect_code_block.py
import sys
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

def inspect():
    print("🕵️‍♂️ 正在连接 Chrome (9527)...")
    opts = Options()
    opts.add_experimental_option("debuggerAddress", "127.0.0.1:9527")
    try:
        driver = webdriver.Chrome(options=opts)
    except:
        print("❌ 连接失败，请确保服务端已启动"); return

    # 1. 查找所有的代码块
    print("🔍 扫描代码块...")
    # 尝试定位包含 "subprocess" 的那个代码块
    code_blocks = driver.find_elements(By.TAG_NAME, "code")
    target_block = None
    
    for block in code_blocks:
        if "subprocess.run" in block.text:
            target_block = block
            break
            
    if not target_block:
        # 再试试 pre
        pre_blocks = driver.find_elements(By.TAG_NAME, "pre")
        for block in pre_blocks:
            if "subprocess.run" in block.text:
                target_block = block
                break

    if target_block:
        print("\n✅ 找到了目标代码块！")
        print("-" * 50)
        # 获取 HTML 源码
        html = target_block.get_attribute('innerHTML')
        # 打印前 1000 个字符，重点看 subprocess 附近
        start_idx = html.find("subprocess.run")
        print(html[start_idx:start_idx+500])
        print("-" * 50)
        print("💡 请把上面这段 HTML 截图或复制发给我，我来写清洗正则。")
    else:
        print("❌ 没找到包含 'subprocess.run' 的代码块，请确保当前网页上有这段对话。")

if __name__ == "__main__":
    inspect()
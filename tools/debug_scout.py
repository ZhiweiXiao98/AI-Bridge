# filename: tools/debug_scout.py
import sys
import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# 确保能导入项目模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def scout_mission():
    print("🕵️‍♂️ [Scout] 侦查兵已就位，准备接入浏览器...")
    
    opts = Options()
    opts.add_experimental_option("debuggerAddress", "127.0.0.1:9527")
    
    try:
        driver = webdriver.Chrome(options=opts)
    except Exception as e:
        print(f"❌ [Scout] 连接失败: {e}")
        print("请确保 start_server.py 已启动且 Chrome 正在运行")
        return

    print("✅ [Scout] 成功接入战场")
    
    # 1. 锁定会话列表
    sessions = driver.find_elements(By.CSS_SELECTOR, ".session")
    print(f"📋 [Scout] 发现 {len(sessions)} 个会话")
    
    if len(sessions) < 2:
        print("⚠️ [Scout] 会话太少，无法执行切换测试")
        return

    # 找到当前未激活的第一个会话
    target_session = None
    for s in sessions:
        if "active" not in s.get_attribute("class"):
            target_session = s
            break
            
    if not target_session:
        print("⚠️ [Scout] 没找到可切换的目标")
        target_session = sessions[-1]

    print(f"🎯 [Scout] 锁定目标: {target_session.text.split()[0]}...")
    
    # 2. 监控 Scroll Top
    scroll_script = """
    var c = document.querySelector('div[class*="n-scrollbar-container"][class*="chat"]');
    if (!c) c = document.querySelector('div.n-scrollbar-container');
    return c ? {top: c.scrollTop, height: c.scrollHeight} : {top: -1, height: -1};
    """
    
    state_0 = driver.execute_script(scroll_script)
    print(f"📏 [T-0] 初始状态: Top={state_0['top']}, Height={state_0['height']}")
    
    # 3. 执行切换
    print("⚡ [Scout] 点击切换！")
    target_session.click()
    t_start = time.time()
    
    # 4. 高频采样 (20Hz)
    log_data = []
    for i in range(40): # 监控 2 秒
        state = driver.execute_script(scroll_script)
        t_now = time.time() - t_start
        print(f"⏱️ [{t_now:.2f}s] Top={state['top']}, Height={state['height']}")
        
        # 检测是否有内容加载 (高度突变)
        if state['height'] != state_0['height'] and state_0['height'] != -1:
             print(f"🚀 [Scout] 发现内容加载变动！(Diff: {state['height'] - state_0['height']})")
             state_0 = state # update baseline
             
        time.sleep(0.05)
        
    print("🕵️‍♂️ [Scout] 侦查结束。请分析日志：")
    print("1. 如果 Height 变动前 Top 就变了 -> 网页自带自动滚动")
    print("2. 如果 Top 始终稳定 -> 是 Worker 在后面手动滚的")

if __name__ == "__main__":
    scout_mission()
# filename: tools/run_tests.py
import sys
import os
import subprocess
import json
import time
from datetime import datetime

def run_tests(target="tests/", output_file="test_report.json"):
    """
    通用测试运行器 (Host/Docker 兼容版)
    直接使用当前 Python 环境运行 pytest
    """
    # 获取当前 Python 解释器路径 (宿主机或容器内均可)
    python_exe = sys.executable
    
    print(f"🚀 Starting Test Runner using: {python_exe}")
    print(f"📂 Target: {os.path.abspath(target)}")
    
    # 构建 pytest 命令
    cmd = [
        python_exe, "-m", "pytest", 
        target,
        "-q",               # 安静模式
        "--tb=short",       # 简短堆栈
        "--disable-warnings"
    ]
    
    start_time = time.time()
    
    try:
        # 执行测试 (设置 60s 超时防止死循环)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=60
        )
        
        duration = time.time() - start_time
        success = (result.returncode == 0)
        
        # 简单解析失败详情
        failures = []
        if not success:
            lines = result.stdout.splitlines()
            # 提取最后 10 行作为错误摘要
            failures = [{"title": "Test Failure", "details": lines[-10:]}]
            
        report = {
            "timestamp": datetime.now().isoformat(),
            "env": "Host" if os.name == 'nt' else "Docker",
            "target": target,
            "duration": round(duration, 2),
            "success": success,
            "return_code": result.returncode,
            "stdout": result.stdout[:2000], # 截断
            "stderr": result.stderr[:1000],
            "failures": failures,
            "summary": f"Tests {'PASSED' if success else 'FAILED'} in {duration:.2f}s"
        }
        
        # 写入 JSON 报告
        with open(output_file, "w", encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            
        print(f"✅ Test Report Generated: {output_file}")
        print(f"📊 Result: {report['summary']}")
        
        if not success:
            print(f"❌ {len(failures)} Failures Detected")
            if failures:
                print("📝 Failure Details:")
                for line in failures[0]['details']:
                    print(f"  > {line}")
            
        return report

    except subprocess.TimeoutExpired:
        print("❌ Test Execution Timed Out!")
        return {"success": False, "error": "Timeout"}
    except Exception as e:
        print(f"❌ Runner Error: {e}")
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "tests/"
    if not os.path.exists(target_dir):
        print(f"⚠️ Target directory '{target_dir}' not found.")
        # 如果是 docker 环境，可能是挂载问题；如果是 Host，可能是路径不对
        # 尝试默认路径
        if os.path.exists("tests"): target_dir = "tests"
        
    run_tests(target_dir)
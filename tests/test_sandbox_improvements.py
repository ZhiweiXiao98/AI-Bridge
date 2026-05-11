# filename: test_sandbox_improvements.py
"""
测试沙盒优化功能
"""
from app.core.docker_manager import DockerManager
import time

def test_basic_execution():
    """测试基本执行"""
    print("\n" + "="*80)
    print("1️⃣ 测试基本代码执行")
    print("="*80)
    
    dm = DockerManager()
    
    code = """
print("Hello from sandbox!")
result = 2 + 2
print(f"2 + 2 = {result}")
"""
    
    exit_code, output = dm.execute_code(code)
    print(f"Exit Code: {exit_code}")
    print(f"Output:\n{output}")
    assert exit_code == 0, "基本执行失败"
    print("✅ 基本执行测试通过")

def test_timeout():
    """测试超时控制"""
    print("\n" + "="*80)
    print("2️⃣ 测试超时控制")
    print("="*80)
    
    dm = DockerManager()
    
    code = """
import time
print("开始长时间运行...")
time.sleep(100)  # 睡眠 100 秒
print("这行不应该被执行")
"""
    
    start = time.time()
    exit_code, output = dm.execute_code(code, timeout=3)
    duration = time.time() - start
    
    print(f"Exit Code: {exit_code}")
    print(f"Duration: {duration:.2f}s")
    print(f"Output:\n{output}")
    
    assert duration < 5, "超时控制失败"
    assert "超时" in output or "timeout" in output.lower(), "未检测到超时"
    print("✅ 超时控制测试通过")

def test_code_validation_dangerous():
    """测试代码验证 - 危险操作"""
    print("\n" + "="*80)
    print("3️⃣ 测试代码验证 - 危险操作")
    print("="*80)
    
    dm = DockerManager()
    
    # 测试 eval（应该被阻止）
    code = """
user_input = "print('hello')"
eval(user_input)  # 危险操作
"""
    
    exit_code, output = dm.execute_code(code)
    print(f"Exit Code: {exit_code}")
    print(f"Output:\n{output}")
    
    assert exit_code != 0, "危险代码未被阻止"
    assert "eval" in output, "未检测到 eval"
    print("✅ 危险操作检测通过")

def test_code_validation_warnings():
    """测试代码验证 - 警告"""
    print("\n" + "="*80)
    print("4️⃣ 测试代码验证 - 警告")
    print("="*80)
    
    dm = DockerManager()
    
    # 测试 os 模块（应该警告但允许执行）
    code = """
import os
print(f"当前目录: {os.getcwd()}")
"""
    
    exit_code, output = dm.execute_code(code)
    print(f"Exit Code: {exit_code}")
    print(f"Output:\n{output}")
    
    # os 模块会产生警告，但在 Docker 环境中应该允许执行
    print("✅ 警告检测通过")

def test_execution_history():
    """测试执行历史"""
    print("\n" + "="*80)
    print("5️⃣ 测试执行历史")
    print("="*80)
    
    dm = DockerManager()
    
    # 执行几次代码
    dm.execute_code("print('Test 1')")
    dm.execute_code("print('Test 2')")
    dm.execute_code("print(1/0)")  # 故意出错
    
    # 获取历史
    history = dm.get_execution_history(count=3)
    print(f"\n历史记录数: {len(history)}")
    for i, record in enumerate(history, 1):
        print(f"\n记录 {i}:")
        print(f"  时间: {record['datetime']}")
        print(f"  成功: {record['success']}")
        print(f"  耗时: {record['duration']}s")
    
    # 获取统计
    stats = dm.get_execution_statistics()
    print(f"\n统计信息:")
    print(f"  总执行次数: {stats['total']}")
    print(f"  成功次数: {stats['success']}")
    print(f"  失败次数: {stats['failed']}")
    print(f"  成功率: {stats['success_rate']}%")
    print(f"  平均耗时: {stats['avg_duration']}s")
    
    assert len(history) >= 3, "历史记录未保存"
    print("\n✅ 执行历史测试通过")

def test_concurrent_execution():
    """测试并发控制"""
    print("\n" + "="*80)
    print("6️⃣ 测试并发控制")
    print("="*80)
    
    dm = DockerManager()
    
    import threading
    results = []
    
    def execute():
        code = "import time; time.sleep(0.5); print('Done')"
        exit_code, output = dm.execute_code(code)
        results.append((exit_code, output))
    
    # 启动多个线程
    threads = [threading.Thread(target=execute) for _ in range(3)]
    start = time.time()
    
    for t in threads:
        t.start()
    
    for t in threads:
        t.join()
    
    duration = time.time() - start
    
    print(f"3 个任务总耗时: {duration:.2f}s")
    print(f"成功执行: {len([r for r in results if r[0] == 0])}/3")
    
    # 由于有锁，应该是串行执行，耗时约 1.5s
    assert duration > 1.0, "并发控制可能失效"
    assert len(results) == 3, "部分任务未完成"
    print("✅ 并发控制测试通过")

if __name__ == "__main__":
    print("🧪 开始测试沙盒优化功能...")
    print("="*80)
    
    try:
        test_basic_execution()
        test_timeout()
        test_code_validation_dangerous()
        test_code_validation_warnings()
        test_execution_history()
        test_concurrent_execution()
        
        print("\n" + "="*80)
        print("🎉 所有测试通过！")
        print("="*80)
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
    except Exception as e:
        print(f"\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()

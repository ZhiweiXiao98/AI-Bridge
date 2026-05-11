# filename: tests/test_pending_message.py
"""
测试需求 2：待发消息附加到工具执行结果
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.worker import WorkerThread


def test_pending_message():
    print("\n" + "="*60)
    print("测试：待发消息功能")
    print("="*60)
    
    # WorkerThread 不接受参数，直接初始化
    worker = WorkerThread()
    
    # 测试 1：设置和获取
    print("\n[测试 1] 设置和获取待发消息")
    worker.set_pending_message("测试消息", [])
    pending = worker.get_and_clear_pending_message()
    print("✅ 通过" if pending and pending["text"] == "测试消息" else "❌ 失败")
    
    # 测试 2：清除后为空
    print("\n[测试 2] 获取后应该清除")
    pending_again = worker.get_and_clear_pending_message()
    print("✅ 通过" if pending_again is None else "❌ 失败")
    
    print("\n" + "="*60)


if __name__ == "__main__":
    test_pending_message()

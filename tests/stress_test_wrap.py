# filename: tests/stress_test_wrap.py
import json

def stress_test():
    print("🧪 正在进行单行超长代码压力测试...")
    
    # 下面这是一行真正的、未截断的、超长的 Python 代码
    # 它模拟了复杂的单行 JSON 序列化数据或超长字符串常量
    # 它的长度足以在任何正常的显示器上触发多次折行
    
    super_long_data = {"id": "TEST_001", "description": "This is a stress test for the Monaco Editor wrapper detection algorithm.", "payload": "A" * 50 +     "B" * 50 + "C" * 50 + "This string is designed to be extremely long to force the browser to wrap it visually. If the parser incorrectly adds a     newline character here, the Python syntax will be broken because string literals cannot span multiple lines without a backslash or triple quotes.     However, with the new Line Number Anchor logic, the parser should detect that these wrapped visual lines do not have corresponding line numbers in     the left margin, and therefore should merge them back into a single logical line. " * 5 + "END_OF_PAYLOAD", "metadata": {"created_at": "2023-10-27",     "author": "AI_Bridge_Architect", "tags": ["stress", "test", "wrapping", "monaco", "dom", "parsing", "selenium", "python", "automation",     "resilience"], "nested_data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 100, 200, 300, 400, 500, 600, 700, 800, 900,     1000]}}
    
    # 验证数据完整性
    try:
        # 如果解析器错误地插入了换行符，上面的 dict 定义会报 SyntaxError
        serialized = json.dumps(super_long_data)
        print(f"✅ 成功解析长对象，序列化长度: {len(serialized)}")
        print("🎉 V7.1 解析器验证通过！自动折行已被正确处理。")
    except Exception as e:
        print(f"❌ 测试失败: {e}")

if __name__ == "__main__":
    stress_test()
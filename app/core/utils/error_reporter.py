# filename: app/core/utils/error_reporter.py
class ErrorReporter:
    @staticmethod
    def generate_report(raw_log):
        lines = raw_log.split('\n')
        errors = []
        capture = False
        buffer = []
        for line in lines:
            if (line.startswith("_________________") and ("ERROR" in line or "FAIL" in line)) or line.startswith("E   "):
                capture = True
                buffer.append(line)
            elif capture:
                if line.startswith("=================") or line.startswith("_______"):
                    capture = False
                    if buffer: errors.append("\n".join(buffer))
                    buffer = []
                else:
                    buffer.append(line)
        summary = []
        for line in lines:
            if "FAILED" in line and "::" in line:
                summary.append(f"- {line.strip()}")
        report = "## 🐛 测试失败报告 (Test Failure Report)\n\n"
        if summary:
            report += "### 🔴 失败用例摘要\n" + "\n".join(summary) + "\n\n"
        if errors:
            report += "### 📜 详细错误堆栈\n```python\n"
            for err in errors[:3]: 
                report += err + "\n"
            report += "```\n"
        report += "\n> 请根据上述堆栈分析原因，并给出修复后的完整代码。\n"
        return report
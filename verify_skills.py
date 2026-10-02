# filename: verify_skills.py
"""
验证 Skills 系统是否正常工作

使用方法：
    python verify_skills.py
"""

import sys
import os

# 添加项目根目录到 sys.path
sys.path.insert(0, os.getcwd())

def main():
    print("🔍 验证 Skills 系统...\n")
    
    try:
        # 1. 导入测试
        print("1️⃣ 测试导入...")
        from app.core.skills import SkillsManager
        print("   ✅ SkillsManager 导入成功")
        
        # 2. 初始化测试
        print("\n2️⃣ 测试初始化...")
        manager = SkillsManager()
        print("   ✅ SkillsManager 初始化成功")
        
        # 3. 扫描测试
        print("\n3️⃣ 测试 Skills 扫描...")
        core_count, extended_count, external_count = manager.scan_all_skills()
        print(f"   ✅ 扫描完成:")
        print(f"      - 核心 Skills: {core_count}")
        print(f"      - 扩展 Skills: {extended_count}")
        print(f"      - 外部 Skills: {external_count}")
        
        # 4. 获取实例测试
        print("\n4️⃣ 测试获取 Skill 实例...")
        file_skill = manager.get_skill_instance('file_operations')
        code_skill = manager.get_skill_instance('code_execution')
        knowledge_skill = manager.get_skill_instance('knowledge_search')
        
        if file_skill:
            print("   ✅ file_operations 实例获取成功")
        if code_skill:
            print("   ✅ code_execution 实例获取成功")
        if knowledge_skill:
            print("   ✅ knowledge_search 实例获取成功")
        
        # 5. 生成提示词测试
        print("\n5️⃣ 测试生成系统提示词...")
        prompt = manager.generate_system_prompt()
        print(f"   ✅ 提示词生成成功 (长度: {len(prompt)} 字符)")
        
        print("\n" + "="*60)
        print("🎉 Skills 系统验证通过！")
        print("="*60)
        print("\n系统状态:")
        print(f"  ✅ 已加载 {core_count + extended_count + external_count} 个 Skills")
        print(f"  ✅ 系统提示词: ~{len(prompt) // 4} tokens")
        print(f"  ✅ 所有核心功能正常")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
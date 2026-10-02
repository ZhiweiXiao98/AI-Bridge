#!/usr/bin/env python3
"""
Skills 系统提示词生成脚本

用途：
- 扫描所有 Skills
- 生成系统提示词
- 保存到指定文件或输出到控制台

使用方法：
    python tools/generate_skills_prompt.py
    python tools/generate_skills_prompt.py --output custom_prompt.md
    python tools/generate_skills_prompt.py --stdout
"""

import sys
import os
import argparse

# 添加项目根目录到 sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.core.skills import SkillsManager


def main():
    parser = argparse.ArgumentParser(description='生成 Skills 系统提示词')
    parser.add_argument(
        '--output', '-o',
        default='app/core/skills/GENERATED_PROMPT.md',
        help='输出文件路径（默认: app/core/skills/GENERATED_PROMPT.md）'
    )
    parser.add_argument(
        '--stdout',
        action='store_true',
        help='输出到控制台而不是文件'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='显示统计信息'
    )
    
    args = parser.parse_args()
    
    print("🔍 扫描 Skills...")
    
    # 初始化 SkillsManager
    manager = SkillsManager()
    
    # 扫描所有 Skills
    core_count, extended_count, external_count = manager.scan_all_skills()
    
    print(f"✅ 扫描完成:")
    print(f"  - 核心 Skills: {core_count}")
    print(f"  - 扩展 Skills: {extended_count}")
    print(f"  - 外部 Skills: {external_count}")
    print(f"  - 总计: {core_count + extended_count + external_count}")
    
    # 生成系统提示词
    print("\n📝 生成系统提示词...")
    prompt = manager.generate_system_prompt()
    
    # 统计信息
    if args.stats or not args.stdout:
        lines = prompt.count('\n')
        chars = len(prompt)
        tokens = chars // 4  # 粗略估算
        
        print(f"\n📊 统计信息:")
        print(f"  - 行数: {lines}")
        print(f"  - 字符数: {chars}")
        print(f"  - 预估 Token: ~{tokens}")
    
    # 输出
    if args.stdout:
        print("\n" + "="*60)
        print("系统提示词内容:")
        print("="*60)
        print(prompt)
    else:
        # 保存到文件
        output_path = args.output
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(prompt)
        
        print(f"\n✅ 已保存到: {output_path}")
    
    # 列出所有 Skills
    if args.stats:
        print("\n📋 Skills 列表:")
        all_skills = manager.list_all_skills()
        
        categories = {}
        for skill in all_skills:
            cat = skill['category']
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(skill)
        
        for cat, skills in sorted(categories.items()):
            print(f"\n  {cat.upper()}:")
            for skill in skills:
                status = "✅" if skill['enabled'] else "❌"
                danger = "⚠️" if skill['dangerous'] else "  "
                code = "🔧" if skill['has_code'] else "📖"
                print(f"    {status} {danger} {code} {skill['name']}")
                print(f"       {skill['description']}")


if __name__ == '__main__':
    main()

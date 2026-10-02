# filename: print_tree.py
import os

def print_tree(startpath):
    # 定义需要忽略的文件夹（垃圾目录）
    IGNORE_DIRS = {
        '.git', '.venv', 'venv', '__pycache__', '.vscode', '.idea', 
        'Chrome_143_Clean_Data', 'chrome_user_data', 'htmlcov', 
        '.pytest_cache', 'bin', 'obj'
    }
    
    for root, dirs, files in os.walk(startpath):
        # 过滤忽略的目录
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        level = root.replace(startpath, '').count(os.sep)
        indent = '    ' * level
        print(f'{indent}{os.path.basename(root)}/')
        subindent = '    ' * (level + 1)
        for f in files:
            # 过滤临时文件
            if f.endswith('.pyc') or f.endswith('.tmp'): continue
            print(f'{subindent}{f}')

if __name__ == '__main__':
    print("="*40)
    print("📂 Project Directory Structure")
    print("="*40)
    print_tree('.')
    print("="*40)
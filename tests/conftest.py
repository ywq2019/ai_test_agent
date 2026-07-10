"""pytest 配置：确保项目根目录在 sys.path 中。"""
import sys
import os

# 项目根目录（tests/ 的上一级）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

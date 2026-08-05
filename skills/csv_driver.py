"""
CSV 数据驱动执行：将 CSV 文件的每一行作为参数注入，对同一个用例执行多次。

CSV 格式：
  - 首行为变量名（与用例 params/body 中的 {{var:变量名}} 对应）
  - 每行产生一条执行记录

示例 CSV：
  username,password,expected_code
  admin,admin123,200
  wrong_user,wrong_pass,401
  ,admin123,400
"""
import csv
import io
from typing import List, Dict, Any


def parse_csv_data(content: str) -> List[Dict[str, str]]:
    """
    解析 CSV 内容，返回变量字典列表。
    首行为列名（变量名），后续每行为一组值。
    """
    reader = csv.DictReader(io.StringIO(content.strip()))
    rows = []
    for row in reader:
        # 过滤空行（所有值为空）
        if any(v.strip() for v in row.values()):
            rows.append({k.strip(): v.strip() for k, v in row.items()})
    return rows

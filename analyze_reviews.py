import pandas as pd
import json
import os
import re
from openai import OpenAI
import tkinter as tk
from tkinter import filedialog

# ================== 配置 ==================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    DEEPSEEK_API_KEY = "sk-1d15abb86fc24802b13f74e92a2cc9be"

print("="*60)
print("多邻国评论情感分析系统")
print("="*60)
print("\n📂 请选择评论CSV文件...")

root = tk.Tk()
root.withdraw()
CSV_FILE_PATH = filedialog.askopenfilename(
    title="选择评论CSV文件",
    filetypes=[("CSV文件", "*.csv")]
)
if not CSV_FILE_PATH:
    print("❌ 未选择文件")
    exit()
print(f"✅ 已选择: {CSV_FILE_PATH}")

OUTPUT_DIR = os.path.dirname(CSV_FILE_PATH) + "_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# ================== 自动识别提取 ==================
def extract_comments_auto(file_path):
    """纯自动识别 - 不针对任何特定格式"""
    
    # 读取文件
    try:
        df = pd.read_csv(file_path, encoding='utf-8')
        encoding_used = 'utf-8'
    except:
        try:
            df = pd.read_csv(file_path, encoding='gbk')
            encoding_used = 'gbk'
        except:
            try:
                df = pd.read_csv(file_path, encoding='utf-8-sig')
                encoding_used = 'utf-8-sig'
            except:
                df = pd.read_csv(file_path, encoding='latin1')
                encoding_used = 'latin1'
    
    print(f"✅ 读取成功 (编码: {encoding_used})")
    print(f"📄 文件形状: {df.shape[0]}行 x {df.shape[1]}列")
    print(f"📋 列名: {list(df.columns)}")
    
    # ========== 自动识别每一列的类型 ==========
    def guess_column_type(col_name, sample_values):
        """根据列名和样本值猜测列类型"""
        col_lower = str(col_name).lower().strip()
        
        # 评论文本列
        text_keywords = ['内容', 'text', 'review', '评论', 'comment', 'content', '评价', '正文']
        for kw in text_keywords:
            if kw in col_lower:
                return 'text'
        
        # 用户名列
        user_keywords = ['作者', 'user', 'name', '用户名', 'username', 'author', '昵称', '发表人']
        for kw in user_keywords:
            if kw in col_lower:
                return 'user'
            # 如果列名是纯数字或包含'id'，跳过
        if 'id' in col_lower or col_lower.isdigit():
          return 'unknown'
        
        # 评分列
        score_keywords = ['评分', 'score', '星级', 'rating', '评级', 'star', '打分']
        for kw in score_keywords:
            if kw in col_lower:
                return 'score'
        
        # 标题列
        title_keywords = ['标题', 'title', '主题', 'subject']
        for kw in title_keywords:
            if kw in col_lower:
                return 'title'
        
        # 日期列
        date_keywords = ['时间', 'date', '发表时间', 'created', '发布时间']
        for kw in date_keywords:
            if kw in col_lower:
                return 'date'
        
        # 如果列名不匹配，根据样本值猜测
        if len(sample_values) > 0:
            sample_str = str(sample_values[0]) if pd.notna(sample_values[0]) else ""
            # 如果是纯数字1-5，可能是评分
            if sample_str.isdigit() and int(sample_str) in [1,2,3,4,5]:
                return 'score'
            # 如果长度较长(>20)，可能是评论文本
            if len(sample_str) > 20:
                return 'text'
            # 如果长度适中(3-15)，可能是用户名
            if 3 <= len(sample_str) <= 15:
                return 'user'
        
        return 'unknown'
    
    # 获取每列的样本值（前10个非空值）
    column_samples = {}
    for col in df.columns:
        samples = df[col].dropna().head(10).tolist()
        column_samples[col] = [str(s) for s in samples if str(s) not in ['nan', 'None', '']]
    
    # 猜测每列的类型
    column_types = {}
    for col in df.columns:
        col_type = guess_column_type(col, column_samples.get(col, []))
        column_types[col] = col_type
    
    print(f"\n🔍 自动识别结果:")
    for col, ctype in column_types.items():
        if ctype != 'unknown':
            print(f"   {col} → {ctype}")
    
    # 找出各类型对应的列
    text_cols = [col for col, typ in column_types.items() if typ == 'text']
    user_cols = [col for col, typ in column_types.items() if typ == 'user']
    score_cols = [col for col, typ in column_types.items() if typ == 'score']
    
    # 如果有多个，取第一个
    text_col = text_cols[0] if text_cols else None
    user_col = user_cols[0] if user_cols else None
    score_col = score_cols[0] if score_cols else None
    
    print(f"\n📌 最终采用:")
    print(f"   评论文本列: {text_col if text_col else '未识别'}")
    print(f"   用户名列: {user_col if user_col else '未识别'}")
    print(f"   评分列: {score_col if score_col else '未识别'}")
    
    # ========== 提取评论 ==========
    comments = []
    
    # 遍历每一行
    for idx, row in df.iterrows():
        try:
            # 提取文本
            comment = ""
            if text_col and pd.notna(row[text_col]):
                comment = str(row[text_col]).strip()
            
            # 如果没有识别到文本列，尝试所有列找最长的字符串
            if not comment or len(comment) < 5:
                for col in df.columns:
                    if pd.notna(row[col]):
                        val = str(row[col]).strip()
                        if len(val) > len(comment) and len(val) >= 10:
                            comment = val
            
            if not comment or len(comment) < 3:
                continue
            
            # 提取用户名
            user_name = "匿名用户"
            if user_col and pd.notna(row[user_col]):
                user_name = str(row[user_col]).strip()
                if user_name.lower() in ['nan', 'none', '']:
                    user_name = "匿名用户"
            else:
                # 尝试找短字段作为用户名
                for col in df.columns:
                    if pd.notna(row[col]):
                        val = str(row[col]).strip()
                        if 2 <= len(val) <= 20 and val not in [comment, user_name]:
                            user_name = val
                            break
            
            # 提取评分
            score = 3
            if score_col and pd.notna(row[score_col]):
                try:
                    score_str = str(row[score_col]).strip()
                    digits = re.findall(r'\d+', score_str)
                    if digits:
                        score = int(digits[0])
                        if score > 5:
                            score = 5
                except:
                    pass
            else:
                # 尝试找1-5的数字作为评分
                for col in df.columns:
                    if pd.notna(row[col]):
                        val = str(row[col]).strip()
                        if val.isdigit() and 1 <= int(val) <= 5:
                            score = int(val)
                            break
            
            comments.append({
                'userName': user_name,
                'score': score,
                'text': comment
            })
        except Exception as e:
            continue
    
    # 去重
    unique = []
    seen = set()
    for c in comments:
        key = c['text'][:80]
        if key not in seen:
            seen.add(key)
            unique.append(c)
    
    print(f"\n✅ 共提取 {len(unique)} 条有效评论")
    
    if len(unique) > 0:
        print("\n📝 前5条示例:")
        for i, c in enumerate(unique[:5]):
            print(f"   {i+1}. {c['userName']} ({c['score']}星): {c['text'][:50]}...")
    
    return unique

# ================== 分析评论 ==================
def analyze_comment(user_name, score, text):
    prompt = f"""分析这条用户评论：
用户：{user_name}
评分：{score}星
评论：{text}

只输出JSON，不要有其他内容：
{{"sentiment":"正面/负面/中性","issue":"一句话总结核心问题","urgency":1-5}}"""
    
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    result = json.loads(resp.choices[0].message.content)
    result['userName'] = user_name
    result['score'] = score
    result['comment_preview'] = text[:80]
    return result

# ================== 主程序 ==================
print("\n🔍 步骤1: 自动识别并提取评论...")
comments = extract_comments_auto(CSV_FILE_PATH)

if len(comments) == 0:
    print("❌ 没有找到评论！")
    exit()

print(f"\n📝 步骤2: 分析 {len(comments)} 条评论...")

results = []
total = len(comments)
for i, c in enumerate(comments):
    print(f"   分析 {i+1}/{total}: {c['userName']} ({c['score']}星)")
    try:
        r = analyze_comment(c['userName'], c['score'], c['text'])
        results.append(r)
    except Exception as e:
        print(f"     出错: {e}")
        results.append({
            'sentiment': '错误',
            'issue': str(e),
            'urgency': 0,
            'userName': c['userName'],
            'score': c['score'],
            'comment_preview': c['text'][:80]
        })

# 保存结果
df = pd.DataFrame(results)
csv_path = os.path.join(OUTPUT_DIR, "完整分析结果.csv")
df.to_csv(csv_path, index=False, encoding='utf-8-sig')
print(f"\n💾 结果已保存: {csv_path}")

# 统计
print("\n" + "="*60)
print("📊 统计结果")
print("="*60)

print("\n情感分布:")
sentiment_counts = df['sentiment'].value_counts()
for s, c in sentiment_counts.items():
    print(f"   {s}: {c}条 ({c/len(df)*100:.1f}%)")

print("\n原始评分分布:")
score_counts = df['score'].value_counts().sort_index()
for s in range(1, 6):
    cnt = score_counts.get(s, 0)
    if cnt > 0:
        print(f"   {s}星: {cnt}条")

print("\n紧急问题TOP5:")
urgent = df.sort_values('urgency', ascending=False).head(5)
for i, row in urgent.iterrows():
    print(f"   [{row['urgency']}分] {row['issue'][:55]}")

print("\n" + "="*60)
print("✅ 完成！")
print("="*60)
# 英语单词学习系统 — 测试与验证计划 (Test & Validation Document)

> **版本**: v1.0
> **创建日期**: 2026-08-04
> **状态**: 初稿
> **关联文档**: [RD.md](RD.md) v1.2, [AD.md](AD.md) v1.0

---

## 目录

1. [测试策略概述](#1-测试策略概述)
2. [测试分层](#2-测试分层)
3. [模块测试用例](#3-模块测试用例)
4. [AI 输出验证](#4-ai-输出验证)
5. [Agentic AI 自动验证方案](#5-agentic-ai-自动验证方案)
6. [测试环境与数据](#6-测试环境与数据)
7. [执行计划](#7-执行计划)

---

## 1. 测试策略概述

### 1.1 测试金字塔

```
            ╱───────╲
           ╱   E2E   ╲          ~10 个场景：全流程手动 / 半自动
          ╱───────────╲
         ╱  Integration╲        ~30 个用例：Django View + DB + API Mock
        ╱───────────────╲
       ╱    Unit Tests    ╲      ~60 个用例：Model, Service, Utility 函数
      ╱───────────────────╲
     ╱   Static / Lint     ╲     ruff, mypy, bandit
    ╱───────────────────────╲
```

### 1.2 核心原则

| 原则 | 说明 |
|------|------|
| **确定性优先** | 所有非 AI 的逻辑必须有确定性的单元测试覆盖 |
| **AI 输出用 AI 验证** | 文章/测验质量无法用断言覆盖，引入 Agentic AI 评判 |
| **Mock DeepSeek** | 集成测试中 Mock API 调用，避免依赖外部服务 |
| **数据库隔离** | 集成测试使用内存 SQLite（`:memory:`），互不干扰 |
| **可重现** | 使用固定种子和 fixture，任何测试 failure 可精确重现 |

### 1.3 测试工具

| 工具 | 用途 |
|------|------|
| `pytest` | 测试框架 |
| `pytest-django` | Django 测试集成 |
| `pytest-cov` | 覆盖率报告 |
| `pytest-mock` | Mock 工具 |
| `responses` 或 `httpx-mock` | Mock HTTP 请求（DeepSeek API） |
| `factory_boy` | 测试数据工厂 |
| `ruff` | Lint |
| `mypy` | 类型检查 |
| `bandit` | 安全检查 |
| Claude Agent SDK | **Agentic AI 验证**（详见第 5 章） |

---

## 2. 测试分层

### 2.1 静态检查 (Static)

```bash
ruff check .                    # 代码风格
mypy . --strict                 # 类型安全（渐进引入）
bandit -r config/ accounts/ wordbank/ learning/  # 安全扫描
```

### 2.2 单元测试 (Unit)

**范围**：纯逻辑函数，无 I/O、无 DB、无 HTTP。

```
learning/tests/unit/
├── test_services.py            # word_selection, mark_mastered, daily_limit, cleanup
├── test_spaced_repetition.py   # SM-2 间隔计算、复习推进、到期检测
├── test_ai_parsing.py          # DeepSeek JSON 解析、格式校验
├── test_highlight.py           # 文章高亮渲染（词边界匹配、子串处理）
└── test_config.py              # 配置读取、默认值、缺失处理
```

**示例 — 间隔重复测试**：
```python
# learning/tests/unit/test_spaced_repetition.py
from datetime import datetime, timedelta, timezone
from learning.services import schedule_review, advance_review_interval

def test_schedule_review_sets_initial_interval(db, user, word):
    status = create_word_status(user, word, status="learning")
    schedule_review(status)
    assert status.status == "mastered"
    assert status.review_interval == 1           # 第 1 级: 1 天
    assert status.next_review_at is not None

def test_advance_review_1_to_3(db, user, word):
    status = create_word_status(user, word, status="mastered", interval=1)
    advance_review_interval(status)
    assert status.review_interval == 3           # 1→3

def test_advance_review_caps_at_60(db, user, word):
    status = create_word_status(user, word, status="mastered", interval=60)
    advance_review_interval(status)
    assert status.review_interval == 60          # 60 封顶

def test_process_due_reviews(db, user, word):
    yesterday = datetime.now(timezone.utc) - timedelta(days=2)
    status = create_word_status(user, word, status="mastered",
                                 interval=1, next_review=yesterday)
    process_due_reviews()
    status.refresh_from_db()
    assert status.status == "review"             # 到期自动进入待复习
```

### 2.3 集成测试 (Integration)

**范围**：Django View + Model + DB + Mocked API。

```
learning/tests/integration/
├── test_views_article.py       # 文章生成 GET/POST、权限、重生成
├── test_views_quiz.py          # 测验提交、计分、跳过
├── test_views_word_review.py   # 单词去留、批量操作、恢复
├── test_views_history.py       # 历史列表、分页、24 篇限制
├── test_views_auth.py          # 登录、登出、重定向
├── test_admin_views.py         # CSV 导入、配置编辑
└── test_api_error_handling.py  # DeepSeek 超时、格式错误、部分成功
```

**示例 — Mock DeepSeek API 的文章生成集成测试**：
```python
# learning/tests/integration/test_views_article.py
import pytest
from django.urls import reverse

@pytest.fixture
def mock_deepseek(httpx_mock):
    """Mock DeepSeek API 返回合法 JSON"""
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/chat/completions",
        json={
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "title": "The Future of AI",
                        "content": "Artificial intelligence is transforming...",
                        "hit_words": ["transform", "algorithm"],
                        "glossary": {"transform": "to change completely", "algorithm": "a set of rules"}
                    })
                }
            }]
        }
    )

def test_generate_article_success(client, user, word_bank, mock_deepseek):
    client.force_login(user)
    response = client.post(reverse("learning:generate_article"), {
        "word_bank_id": word_bank.id,
        "interests": ["technology"],
        "sentence_complexity": 5,
    })
    assert response.status_code == 200
    assert "The Future of AI" in response.content.decode()
    assert 'class="word-target"' in response.content.decode()  # 高亮标记存在

def test_generate_article_over_limit(client, user):
    """每日超过上限应被拒绝"""
    client.force_login(user)
    DailyUsage.objects.create(user=user, date=date.today(), generation_count=3)
    response = client.post(reverse("learning:generate_article"), data={...})
    assert response.status_code == 403
    assert "daily limit" in response.content.decode().lower()

def test_generate_article_api_timeout(client, user, httpx_mock):
    """API 超时 → 显示错误消息 (D-43)"""
    httpx_mock.add_exception(httpx.ConnectTimeout("Connection timed out"))
    client.force_login(user)
    response = client.post(reverse("learning:generate_article"), data={...})
    assert response.status_code == 200
    assert "unavailable" in response.content.decode().lower()
```

### 2.4 端到端测试 (E2E)

**范围**：完整用户旅程，真实浏览器（可选）。

| # | 场景 | 步骤 | 验证点 |
|---|------|------|--------|
| E2E-01 | 新用户完整学习流程 | 登录 → 选择词库 → 兴趣 → 生成 → 阅读 → 测验 → 标记单词 | 全流程无报错，文章含高亮，测验可提交，单词状态更新 |
| E2E-02 | 跳过测验流程 | 生成文章 → 阅读 → 跳过测验 → 直接进入单词管理 | 测验被跳过但文章保存正常 |
| E2E-03 | 重新生成 | 阅读文章 → 不满 → 重新生成 → 新文章替换 | 新文章覆盖，每日次数仍计 1 次 |
| E2E-04 | 每日上限 | 连续生成 4 次，第 4 次被拒 | 返回上限提示 |
| E2E-05 | 已掌握单词浅色显示 | 某单词已掌握 → 生成新文章 → 单词出现但浅色 | 已掌握单词不在文末目标列表但出现在文章中 |
| E2E-06 | 间隔复习触发 | 标记单词为已掌握 → 模拟 1 天后 → 运行到期检测 → 单词进入 review | 待复习单词出现在下次 AI 单词池 |
| E2E-07 | Admin CSV 导入 | 登录 Admin → 上传 CSV → 验证词库条目数 | 单词正确解析，Tab 分隔 |
| E2E-08 | 历史文章限制 | 生成 25 篇文章 → 第 25 篇后旧文章被清理 | 仅保留最新 24 篇 |
| E2E-09 | 学习热力图 | 连续学习 7 天 → 查看统计页 | 热力图正确显示 7 天活动 |
| E2E-10 | 批量标记 | 文章命中 30 个词 → 点击"全部掌握" | 所有 30 个词状态变为已掌握 |

---

## 3. 模块测试用例

### 3.1 accounts — 用户模块

| ID | 测试项 | 层级 | 输入 | 预期 |
|----|--------|------|------|------|
| UT-A01 | 重定向未登录用户 | Unit | 未登录访问 `/` | 302 → `/account/login/` |
| UT-A02 | 正确密码登录 | Integration | username + password | 302 → `/`, session 创建 |
| UT-A03 | 错误密码拒绝 | Integration | username + wrong | 200, "Invalid credentials" |
| UT-A04 | Profile 默认值 | Unit | 新用户创建 | level=intermediate, complexity=5 |
| UT-A05 | Profile 更新 | Integration | POST nickname, level, goal | 数据库更新成功 |

### 3.2 wordbank — 词库模块

| ID | 测试项 | 层级 | 输入 | 预期 |
|----|--------|------|------|------|
| UT-W01 | CSV 解析 Tab 分隔 | Unit | `"apple\tnoun\t苹果\n"` | Word(word="apple", pos="noun", def="苹果") |
| UT-W02 | CSV 解析空行跳过 | Unit | 含空行的 CSV | 空行忽略，不产生空 Word |
| UT-W03 | CSV 解析词组 | Unit | `"give up\tphrase\t放弃"` | Word(is_phrase=True) |
| UT-W04 | 重复单词拒绝 | Integration | 同词库导入同一单词两次 | `unique_together` 约束抛出 IntegrityError |
| UT-W05 | Admin 词库 CRUD | Integration | Admin 增/删/改单词 | 数据库同步更新 |

### 3.3 learning — 学习核心

| ID | 测试项 | 层级 | 输入 | 预期 |
|----|--------|------|------|------|
| UT-L01 | 单词选取：学习+复习混合 | Unit | 80 learning + 20 review words | word_pool 长度 = 100 |
| UT-L02 | 单词选取：超 500 随机抽取 | Unit | 600 个待学单词 | word_pool 长度 = 500 |
| UT-L03 | 单词选取：排除已掌握 | Unit | 含 mastered 状态的单词 | mastered 不在 pool 中 |
| UT-L04 | 标记已掌握 | Unit | learning→mastered | status=mastered, interval=1, mastered_at 已设置 |
| UT-L05 | 已掌握单词恢复 | Integration | POST restore | status=learning |
| UT-L06 | 已移除单词恢复 | Integration | POST restore | status=learning |
| UT-L07 | 每日上限 0/3 → 允许 | Integration | generation_count=0 | 允许生成 |
| UT-L08 | 每日上限 3/3 → 拒绝 | Integration | generation_count=3 | 拒绝，403 |
| UT-L09 | 文章高亮：目标单词 | Unit | content + hit_words | `<strong class="word-target">word</strong>` |
| UT-L10 | 文章高亮：已掌握单词 | Unit | content + mastered_words | `<span class="word-mastered">word</span>` |
| UT-L11 | 文章高亮：词边界匹配 | Unit | content 含 "able", 不匹配 "table" | 仅 "able" 被高亮 |
| UT-L12 | 测验提交全部正确 | Integration | 5/5 正确 | score=5, answers 已保存 |
| UT-L13 | 测验提交部分正确 | Integration | 3/5 正确 | score=3 |
| UT-L14 | 测验跳过 | Integration | POST skip=true | is_skipped=True, score=None |
| UT-L15 | 批量标记全部掌握 | Integration | POST all_mastered | 所有 hit_words 变为 mastered |
| UT-L16 | 历史文章 24 篇限制 | Integration | 第 25 篇文章生成后 | 旧文章被删除，保留 24 篇 |
| UT-L17 | 文章生成记录每日使用 | Integration | 生成第 N 篇 | DailyUsage 增加 |
| UT-L18 | 学习活动记录 | Integration | 完成测验 | LearningActivity 记录更新 |

### 3.4 DeepSeek API 集成

| ID | 测试项 | 层级 | 输入 | 预期 |
|----|--------|------|------|------|
| UT-D01 | JSON 解析正常 | Unit | 合法 JSON 字符串 | 返回解析后的 dict |
| UT-D02 | JSON 解析异常 | Unit | 非 JSON 文本 | 返回 None（放弃） |
| UT-D03 | 文章内容 word_count 检查 | Unit | 内容长度 | 不强制断，由 AI 评判验证 |
| UT-D04 | hit_words 范围校验 | Unit | 25–50 命中 | 通过 |
| UT-D05 | hit_words 不足告警 | Unit | ≤10 命中 | 记录日志但不阻断 |
| UT-D06 | Quiz 格式校验 | Unit | 5 题含 options | 通过 |
| UT-D07 | Quiz 题数不足 | Unit | 仅 3 题 | 解析失败返回 None |

---

## 4. AI 输出验证

这是本项目最特殊的测试挑战：**如何验证 AI 生成的内容质量？**

### 4.1 可程序化验证的维度（确定性）

这些用传统断言即可覆盖：

| 维度 | 验证方式 | 测试类型 |
|------|----------|----------|
| JSON 结构合法 | `json.loads()` 成功 | Unit |
| 必要字段存在 | `"title" in data` etc. | Unit |
| hit_words 是列表 | `isinstance(data["hit_words"], list)` | Unit |
| glossary 键值对 | `isinstance(data["glossary"], dict)` | Unit |
| Quiz 题目数量 = 5 | `len(quiz["questions"]) == 5` | Unit |
| Quiz 每道题 4 选项 | `len(q["options"]) == 4` | Unit |
| HTML 包含高亮标签 | `class="word-target" in html` | Integration |
| 文章不为空 | `len(content) > 0` | Integration |

### 4.2 需要 AI 评判的维度（非确定性）

这些无法用传统断言衡量，需要 **Agentic AI 评判**：

| 维度 | 说明 | 为什么需要 AI |
|------|------|---------------|
| **自然度** | 目标单词是否自然融入，不刻意 | 人类感知，无规则可表达 |
| **流畅度** | 文章整体语言质量 | 语法/语感需语言模型评判 |
| **内容相关性** | 是否贴合用户选择的兴趣方向 | 需要语义理解 |
| **难度匹配** | 是否匹配设定的句子复杂度 | 语言难度是多维度的 |
| **测验质量** | 题目是否有区分度，选项是否合理 | 干扰项质量需教育评估 |
| **单词覆盖策略** | AI 选取单词是否合理 | 需要平衡质量与数量 |

---

## 5. Agentic AI 自动验证方案 ★

### 5.1 方案概述

```
┌─────────────────────────────────────────────────────┐
│                Agentic AI 验证流水线                    │
│                                                     │
│  1. 测试脚本生成文章 (真实 DeepSeek 或 Mock)           │
│                      ↓                              │
│  2. 文章 + 上下文 → Claude Agent (评判员)             │
│     ┌──────────────────────────────────────┐        │
│     │  Claude 从多个维度独立打分：           │        │
│     │  • 自然度 (1–5)                      │        │
│     │  • 流畅度 (1–5)                      │        │
│     │  • 主题相关性 (1–5)                   │        │
│     │  • 难度匹配 (1–5)                    │        │
│     │  • 目标单词使用率 (百分比)             │        │
│     └──────────────────────────────────────┘        │
│                      ↓                              │
│  3. 结构化输出 → JSON 评判报告                       │
│     { scores: {...}, verdict: "pass"|"warn"|"fail", │
│       issues: [...], suggestions: [...] }           │
│                      ↓                              │
│  4. 汇总 → 质量趋势报告                              │
└─────────────────────────────────────────────────────┘
```

### 5.2 两种验证模式

#### 模式 A: 离线批量验证（推荐用于开发阶段）

在开发/PR 阶段，生成一批样本文章和测验，由 Claude 统一评判。

```
工作流:
  1. 准备 20 组输入参数 (不同兴趣、难度、单词池)
  2. 调用 DeepSeek 生成文章 + 测验 (或用已保存的 fixture)
  3. 对每组输出:
     a. 确定性断言先过滤 (JSON 格式、字段完整性)
     b. 通过断言的进入 AI 评判阶段
     c. Claude 打分并输出结构化报告
  4. 汇总: 通过率、平均分、常见问题模式
```

#### 模式 B: CI 实时评判（推荐用于 PR gate）

每次 PR 时生成少量样本（3–5 篇），由 Claude 评判，低于阈值则 PR 被 block。

```
CI Pipeline:
  pytest (确定性测试)
    → 全部通过
      → 生成 5 篇测试文章 (真实 DeepSeek API)
        → Claude Agent 评判
          → 平均分 ≥ 4.0 → ✅ PR OK
          → 平均分 < 4.0 → ⚠️ 人工审核
```

### 5.3 实现：Claude Agent SDK 评判器

#### 评判 Agent 定义

```yaml
# .claude/agents/quality-judge.md
---
name: quality-judge
description: Evaluates AI-generated English learning articles and quizzes
tools: []
model: sonnet
---

You are a quality evaluator for AI-generated English learning content.

## Evaluation Criteria

For each article, evaluate on a 1–5 scale:

1. **Naturalness**: Do target vocabulary words appear naturally in the text, or do they feel forced/inserted?
   - 5: Words flow seamlessly, reader wouldn't know they were required
   - 1: Words are obviously shoehorned in, disrupting reading flow

2. **Fluency**: Is the English natural and native-like?
   - 5: Native-level prose, appropriate register
   - 1: Awkward phrasing, grammar errors, unnatural collocations

3. **Topic Relevance**: Does the article match the specified interest topic(s)?
   - 5: Clearly and engagingly about the topic(s)
   - 1: Off-topic or barely related

4. **Difficulty Match**: Does the complexity match the requested level (1–9 scale)?
   - 5: Perfect match for target level
   - 1: Way too easy or too hard for target level

5. **Coverage**: What percentage of provided target words were successfully used?
   - 5: >80% used
   - 1: <20% used

For each quiz:
- Are questions genuinely about comprehension (not vocabulary recall)?
- Are incorrect options plausible distractors?
- Is the correct answer clearly supported by the article?

## Output

Always output your evaluation as a structured JSON object with this schema.
```

#### 验证脚本（伪代码）

```python
# tests/agentic/quality_verification.py
"""
Agentic AI 验证脚本。

通过 Claude Agent SDK 评估 DeepSeek 生成的文章和测验质量。

用法:
    python tests/agentic/quality_verification.py --samples 5
"""

import json
import pytest
from pathlib import Path

# 假设有一个 Claude Agent SDK 的 Python 客户端
# 或者通过 subprocess 调用 Claude Code CLI


def build_evaluation_prompt(article: dict, quiz: dict, params: dict) -> str:
    """构建评判 prompt"""
    return f"""
Evaluate this AI-generated English learning article and quiz.

### Generation Parameters
- Interest topic(s): {params['interests']}
- Target complexity: {params['sentence_complexity']}/9
- Target word count: ~{params['target_word_count']}
- Target words provided: {params['word_count']}
- Target words used (hit): {len(article['hit_words'])}

### Article
Title: {article['title']}
Content:
{article['content']}

### Words Used
{json.dumps(article['glossary'], indent=2)}

### Quiz Questions
{json.dumps(quiz['questions'], indent=2)}

---

Evaluate the article on naturalness, fluency, topic relevance, difficulty match,
and word coverage. Evaluate the quiz on comprehension focus and distractor quality.

Return your evaluation as JSON:
{{
  "article_scores": {{
    "naturalness": <1-5>,
    "fluency": <1-5>,
    "topic_relevance": <1-5>,
    "difficulty_match": <1-5>,
    "coverage": <1-5>
  }},
  "quiz_scores": {{
    "comprehension_focus": <1-5>,
    "distractor_quality": <1-5>
  }},
  "overall_verdict": "pass" | "warn" | "fail",
  "issues": ["issue1", "issue2"],
  "suggestions": ["suggestion1", "suggestion2"]
}}
"""


def evaluate_with_claude(prompt: str) -> dict:
    """
    调用 Claude 进行评判。
    
    实现方式选一：
    A. 使用 Anthropic Python SDK 直接调用 Messages API
    B. 使用 `claude` CLI: subprocess.run(["claude", "ask", "--json", prompt])
    C. 使用 Claude Agent SDK 的 StructuredOutput
    """
    # 方案 A: 直接 API 调用
    import anthropic
    
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    # 从 response 中提取 JSON
    text = response.content[0].text
    # 解析 JSON (可能在 markdown code block 中)
    return extract_json(text)


def test_article_quality():
    """
    生成文章并由 Claude 评判，断言通过阈值。
    此测试标记为 integration + slow，仅选择性运行。
    """
    params = {
        "interests": ["technology"],
        "sentence_complexity": 5,
        "target_word_count": 500,
        "word_count": 40,
    }
    
    article, quiz = generate_article_and_quiz(params)  # 调用 DeepSeek
    
    # 1. 确定性检查
    assert len(article["content"]) > 0
    assert len(quiz["questions"]) == 5
    
    # 2. AI 评判
    prompt = build_evaluation_prompt(article, quiz, params)
    evaluation = evaluate_with_claude(prompt)
    
    # 3. 断言
    scores = evaluation["article_scores"]
    assert scores["naturalness"] >= 3, f"Naturalness too low: {scores['naturalness']}"
    assert scores["fluency"] >= 3, f"Fluency too low: {scores['fluency']}"
    assert evaluation["overall_verdict"] in ("pass", "warn")
    
    # 4. 保存报告
    Path("tests/reports").mkdir(exist_ok=True)
    with open(f"tests/reports/eval_{timestamp}.json", "w") as f:
        json.dump(evaluation, f, indent=2)
```

### 5.4 运营期持续验证

```
┌──────────────────────────────────────────────┐
│           Agentic AI 持续质量监控              │
│                                              │
│  定期 (如每周) 从生产环境取样                  │
│    ├── 最新 5 篇用户生成的文章                 │
│    ├── Claude 评判 (离线，不影响用户)           │
│    └── 质量趋势报告                            │
│                                              │
│  异常检测:                                    │
│    ├── DeepSeek 模型升级后质量骤降 → 告警       │
│    ├── 某类兴趣/难度下质量持续偏低 → 调整 prompt │
│    └── 单词命中率趋势下降 → 检查单词池逻辑       │
└──────────────────────────────────────────────┘
```

### 5.5 评估 — 可行性结论

| 维度 | 评估 |
|------|------|
| **技术可行性** | ✅ 高 — Claude 可以通过 SDK 直接调用，结构化输出稳定 |
| **评判可靠性** | ⚠️ 中等 — AI 评判存在主观性，建议多轮取平均 |
| **成本** | ✅ 低 — 每次评判约 500–1000 tokens 输出，Sonnet 成本可控 |
| **延迟** | ✅ 低 — CI 中每次评判约 2–5 秒，批量验证可并行 |
| **覆盖盲区** | ⚠️ 无法检测事实性错误（如文章包含错误知识点），无法验证"单词释义是否准确" |

**建议**：
- Agentic AI 验证作为**补充**而非替代传统测试
- 用于 CI gate 时阈值设低（如 3/5），主要抓明显质量问题
- 在开发阶段人工 review 校准 AI 评判标准
- 保留评判历史日志，观察趋势而非单次分数

---

## 6. 测试环境与数据

### 6.1 测试 Fixture 数据

```python
# conftest.py (pytest fixtures)
import pytest
from django.contrib.auth.models import User
from wordbank.models import WordBank, Word
from learning.models import Interest

@pytest.fixture
def user(db):
    return User.objects.create_user("testuser", password="testpass")

@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser("admin", password="adminpass")

@pytest.fixture
def word_bank(db):
    return WordBank.objects.create(name="上海高考")

@pytest.fixture
def words(word_bank):
    words = []
    for i, (w, pos, defn) in enumerate([
        ("abandon", "verb", "放弃"),
        ("brilliant", "adj", "杰出的"),
        ("consequence", "noun", "结果"),
        # ... 至少 50 个单词用于测试
    ]):
        words.append(Word.objects.create(
            word_bank=word_bank, word=w,
            part_of_speech=pos, definition=defn
        ))
    return words

@pytest.fixture
def interests(db):
    return [
        Interest.objects.create(name="Technology", slug="technology"),
        Interest.objects.create(name="Science", slug="science"),
    ]
```

### 6.2 Mock DeepSeek Response Fixture

```python
@pytest.fixture
def mock_deepseek_article(httpx_mock):
    """标准合法文章响应"""
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/chat/completions",
        json={
            "choices": [{"message": {"content": json.dumps({
                "title": "Test Article",
                "content": "This is a test article with target words.",
                "hit_words": ["test", "target"],
                "glossary": {"test": "a trial", "target": "a goal"}
            })}}]
        }
    )

@pytest.fixture
def mock_deepseek_timeout(httpx_mock):
    """API 超时场景"""
    httpx_mock.add_exception(
        url="https://api.deepseek.com/v1/chat/completions",
        exception=httpx.ConnectTimeout("timeout"),
    )

@pytest.fixture
def mock_deepseek_bad_json(httpx_mock):
    """非法 JSON 场景"""
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "not valid json {{["}}]}},
    )
```

### 6.3 真实 API 测试标记

```python
# pytest 标记，仅在有 API Key 时运行
@pytest.mark.real_api
@pytest.mark.slow
def test_real_deepseek_integration():
    """需要真实 API Key 的集成测试"""
    ...

# 运行方式:
# pytest -m "not real_api"        # 默认跳过
# pytest -m "real_api"            # 仅在配置了 API Key 的环境运行
```

---

## 7. 执行计划

### 7.1 开发阶段测试策略

| 阶段 | 测试范围 | 频率 | 工具 |
|------|----------|------|------|
| 编码时 | Unit tests | 每次保存 | pytest --lf (last failed) |
| 提交前 | Unit + Integration (--fast) | 每次 commit | pre-commit hook |
| PR | 全量 Unit + Integration + Lint | 每个 PR | CI |
| PR (可选) | Agentic AI 评判 (3 samples) | 改动 AI prompt 时 | CI + Claude |
| 发布前 | 全量 + E2E + Agentic 批量 (10 samples) | 每个 release | Manual + Script |

### 7.2 CI 配置（GitHub Actions 示例）

```yaml
# .github/workflows/test.yml
name: Test

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install ruff mypy bandit
      - run: ruff check .
      - run: mypy . --ignore-missing-imports
      - run: bandit -r config/ accounts/ wordbank/ learning/ -ll

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt && pip install pytest pytest-django pytest-cov pytest-mock
      - run: pytest --cov=. --cov-report=html -m "not real_api and not slow"

  agentic-verify:
    if: contains(github.event.head_commit.modified, 'ai.py')  # 仅 AI 相关变更
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -r requirements.txt && pip install anthropic
      - run: python tests/agentic/quality_verification.py --samples 3
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### 7.3 覆盖率目标

| 模块 | 目标覆盖率 | 说明 |
|------|-----------|------|
| `learning/services.py` | ≥ 90% | 核心业务逻辑 |
| `learning/ai.py` | ≥ 80% | AI 调用与解析 |
| `wordbank/services.py` | ≥ 90% | CSV 解析 |
| `accounts/models.py` | ≥ 80% | Profile |
| Views | ≥ 70% | 集成测试覆盖 |
| 总体 | ≥ 75% | |

### 7.4 运行命令速查

```bash
# 全量确定性测试（日常）
pytest -x -m "not real_api and not slow"

# 包含慢速集成测试
pytest -m "not real_api"

# 单模块
pytest learning/tests/unit/ -v

# 覆盖率
pytest --cov=learning --cov=wordbank --cov=accounts --cov-report=term-missing

# Agentic AI 验证（需 Anthropic API Key）
python tests/agentic/quality_verification.py --samples 5

# 仅运行上次失败的测试
pytest --lf

# 新测试优先运行
pytest --nf
```

---

## 附录 A: Agentic AI 评判参考数据流

```
DeepSeek API
    │
    ├──→ Article JSON ──→ 确定性过滤 ──→ 通过 ──→ Claude Judge
    │                                         │
    │                                         ├── 维度 1: 自然度
    │                                         ├── 维度 2: 流畅度
    │                                         ├── 维度 3: 主题相关
    │                                         ├── 维度 4: 难度匹配
    │                                         └── 维度 5: 覆盖率
    │                                              │
    └──→ Quiz JSON ────→ 确定性过滤 ──→ 通过 ──→ Claude Judge
                                                   │
                                                   ├── 维度 6: 理解测试
                                                   └── 维度 7: 干扰项质量
                                                        │
                                                        ▼
                                                  ┌──────────┐
                                                  │ 评判报告  │
                                                  │ JSON     │
                                                  └──────────┘
```

## 附录 B: 评判报告格式

```json
{
  "evaluation_id": "eval_20260804_001",
  "timestamp": "2026-08-04T10:00:00Z",
  "parameters": {
    "interests": ["technology"],
    "sentence_complexity": 5,
    "target_word_count": 500,
    "words_provided": 40,
    "words_used": 32
  },
  "article_scores": {
    "naturalness": 4,
    "fluency": 5,
    "topic_relevance": 4,
    "difficulty_match": 3,
    "coverage": 4
  },
  "quiz_scores": {
    "comprehension_focus": 4,
    "distractor_quality": 3
  },
  "overall_verdict": "pass",
  "issues": [
    "Sentence complexity feels closer to level 7 than requested level 5"
  ],
  "suggestions": [
    "Shorten some compound sentences to better match intermediate difficulty"
  ]
}
```

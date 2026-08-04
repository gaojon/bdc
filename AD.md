# 英语单词学习系统 — 架构设计文档 (Architecture Design)

> **版本**: v1.1
> **创建日期**: 2026-08-04
> **状态**: 已实现，与代码同步
> **关联文档**: [RD.md](RD.md) v1.3

---

## 目录

1. [系统架构概览](#1-系统架构概览)
2. [技术栈](#2-技术栈)
3. [项目结构](#3-项目结构)
4. [数据库设计](#4-数据库设计)
5. [AI 集成设计](#5-ai-集成设计)
6. [核心流程设计](#6-核心流程设计)
7. [URL 路由设计](#7-url-路由设计)
8. [模板设计](#8-模板设计)
9. [配置设计](#9-配置设计)
10. [部署架构](#10-部署架构)
11. [安全设计](#11-安全设计)
12. [间隔重复算法](#12-间隔重复算法)

---

## 1. 系统架构概览

```
┌────────────────────────────────────────────────────┐
│                    浏览器 (Browser)                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ 用户端页面 │  │ Admin 页面 │  │ Django Admin 后台 │  │
│  │(Django   │  │(Django   │  │(内置 Admin)      │  │
│  │Template) │  │Template) │  │                  │  │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
└───────┼─────────────┼────────────────┼─────────────┘
        │             │                │
        │  HTTP       │                │
        ▼             ▼                ▼
┌────────────────────────────────────────────────────┐
│              Django 应用 (Ubuntu Server)             │
│                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ accounts │  │ wordbank │  │    learning      │  │
│  │ 用户模块  │  │ 词库模块  │  │    学习核心       │  │
│  └────┬─────┘  └────┬─────┘  └───────┬──────────┘  │
│       │             │                │              │
│       └─────────────┴────────────────┘              │
│                     │                               │
│              ┌──────┴──────┐                        │
│              │  SQLite DB  │                        │
│              └─────────────┘                        │
│                     │                               │
│              ┌──────┴──────┐                        │
│              │ DeepSeek API│  (外部 HTTP 调用)       │
│              └─────────────┘                        │
└────────────────────────────────────────────────────┘
```

**架构原则**：单体应用，服务器端渲染，无前后端分离。所有业务逻辑在 Django 后端完成，HTML 通过 Django Templates 直接在服务端生成。

---

## 2. 技术栈

| 层级 | 技术 | 版本建议 | 说明 |
|------|------|----------|------|
| 语言 | Python | 3.12+ | |
| Web 框架 | Django | 5.1+ | 自带 Admin、ORM、Auth、Templates |
| 数据库 | SQLite | 3.x (内置) | 单文件，零运维 |
| AI API | DeepSeek | — | 兼容 OpenAI SDK 调用方式 |
| HTTP 客户端 | `httpx` 或 `openai` SDK | — | 调用 DeepSeek API |
| 前端样式 | 纯 CSS 或 Pico.css | — | 轻量 CSS 框架，无需构建工具 |
| 前端交互 | 原生 JavaScript (少量) | — | 仅用于高亮、批量操作等增强交互 |
| 部署 | Gunicorn / uWSGI | — | WSGI 服务器 |
| 进程管理 | systemd | — | 服务自启动和守护 |

> **不引入**：Node.js、npm、Webpack、React/Vue、Redis、Celery、Nginx（内网场景直接用 Django 处理静态文件即可）。

---

## 3. 项目结构

```
bdc/
├── manage.py
├── requirements.txt
│
├── config/                      # Django 项目配置包
│   ├── __init__.py
│   ├── settings.py              # Django 设置
│   ├── urls.py                  # 根 URL 路由
│   ├── wsgi.py                  # WSGI 入口
│   └── app_config.json          # 应用级配置（API Key、限制等）
│
├── accounts/                    # 用户模块
│   ├── __init__.py
│   ├── models.py                # Profile 模型
│   ├── views.py                 # 登录、登出、个人信息
│   ├── urls.py
│   ├── admin.py
│   └── templates/
│       └── accounts/
│           ├── login.html
│           └── profile.html
│
├── wordbank/                    # 词库模块
│   ├── __init__.py
│   ├── models.py                # WordBank, Word
│   ├── views.py                 # 用户端：词库列表、浏览、导入/导出、编辑、标记已掌握
│   ├── urls.py                  # 8 条路由
│   ├── admin.py                 # Admin：CSV 导入、CRUD（注册到 Django Admin）
│   ├── services.py              # CSV 解析、单词查询
│   └── templates/
│       └── wordbank/
│           ├── manage.html      # 词库列表（创建、删除、导出）
│           └── browse.html      # 单词表格（状态列、Edit/Master 按钮、导入/导出）
│
├── learning/                    # 学习核心模块
│   ├── __init__.py
│   ├── models.py                # UserWordStatus, Article, Quiz
│   ├── views.py                 # 文章阅读、测验、单词管理、历史
│   ├── urls.py
│   ├── admin.py
│   ├── services.py              # 核心业务逻辑
│   │   ├── word_selection()     #   从词库中选取单词给 AI
│   │   ├── mark_mastered()      #   标记已掌握
│   │   ├── schedule_review()    #   SM-2 间隔计算
│   │   └── check_daily_limit()  #   每日生成上限
│   ├── ai.py                    # DeepSeek API 调用
│   │   ├── generate_article()   #   生成文章
│   │   ├── generate_quiz()      #   生成测验题
│   │   └── parse_response()     #   解析 JSON 返回
│   └── templates/
│       └── learning/
│           ├── index.html       # 首页（兴趣选择 + 开始学习）
│           ├── article.html     # 文章阅读 + 测验
│           ├── word_review.html # 单词去留管理
│           ├── history.html     # 学习历史
│           └── stats.html       # 学习统计 + 热力图
│
├── templates/                   # 全局模板
│   ├── base.html                # 基础布局
│   └── admin/                   # Admin 自定义模板（按需）
│
├── static/                      # 静态文件
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── main.js              # 少量交互增强
│
└── utils/
    ├── __init__.py
    ├── config.py                # 读取 app_config.json
    └── constants.py             # 枚举值：单词状态、英语水平等
```

---

## 4. 数据库设计

### 4.1 实体关系图 (ERD)

```
┌──────────┐       ┌──────────────┐       ┌──────────┐
│  WordBank │ 1───N │     Word     │       │ Interest │
│  (词库)   │       │   (单词)     │       │ (兴趣)   │
└────┬─────┘       └──────┬───────┘       └────┬─────┘
     │                    │                    │
     │                    │ N                  │ N
     │              ┌─────┴────────┐           │
     │              │UserWordStatus│           │
     │              │ (学习状态)    │           │
     │              └──────┬───────┘           │
     │                     │ N                 │
     │                     │                   │
     │              ┌──────┴───────┐           │
     │              │    User      │───────────┘
     │              │  (Django)    │ N───────M
     │              └──────┬───────┘
     │                     │ 1
     │                     │
     │              ┌──────┴───────┐
     │              │   Article    │───────M
     │              │   (文章)     │
     │              └──────┬───────┘
     │                     │ 1
     │                     │
     │              ┌──────┴───────┐
     │              │    Quiz      │
     │              │   (测验)     │
     │              └──────────────┘
     │
     └──────────────────────────────────── 文章关联词库
```

### 4.2 模型定义

#### accounts / User Profile

扩展 Django 内置 `User` 模型，使用 OneToOne `Profile`：

```python
# accounts/models.py
from django.db import models
from django.contrib.auth.models import User

class Profile(models.Model):
    class Level(models.TextChoices):
        BEGINNER     = "beginner",     "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED     = "advanced",     "Advanced"

    user               = models.OneToOneField(User, on_delete=models.CASCADE)
    nickname           = models.CharField(max_length=64, blank=True)
    english_level      = models.CharField(max_length=16, choices=Level, default=Level.INTERMEDIATE)
    sentence_complexity    = models.IntegerField(default=5)          # 1–9
    daily_word_goal       = models.IntegerField(default=10)         # 用户每日目标
    selected_word_bank_id = models.IntegerField(null=True, blank=True)  # 上次选择的词库

    def __str__(self):
        return f"{self.user.username}'s profile"
```

#### wordbank / WordBank & Word

```python
# wordbank/models.py
class WordBank(models.Model):
    name        = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Word(models.Model):
    word_bank      = models.ForeignKey(WordBank, on_delete=models.CASCADE, related_name="words")
    word           = models.CharField(max_length=255)       # 单词本身
    part_of_speech = models.CharField(max_length=32)        # 词性 e.g. noun, verb, adj, phrase
    definition     = models.CharField(max_length=512)       # 中文解释
    is_phrase      = models.BooleanField(default=False)     # 是否为词组

    class Meta:
        unique_together = ("word_bank", "word")

    def __str__(self):
        return f"{self.word} ({self.part_of_speech})"
```

#### learning / UserWordStatus

```python
# learning/models.py
class UserWordStatus(models.Model):
    class Status(models.TextChoices):
        NEW      = "new",      "New"
        LEARNING = "learning", "Learning"
        MASTERED = "mastered", "Mastered"
        REMOVED  = "removed",  "Removed"
        REVIEW   = "review",   "Review"

    user              = models.ForeignKey(User, on_delete=models.CASCADE, related_name="word_statuses")
    word              = models.ForeignKey(Word, on_delete=models.CASCADE)
    status            = models.CharField(max_length=16, choices=Status, default=Status.NEW)
    occurrence_count  = models.IntegerField(default=0)          # W-07 出现次数
    last_reviewed_at  = models.DateTimeField(null=True, blank=True)
    review_interval   = models.IntegerField(default=0)          # SM-2 当前间隔天数
    next_review_at    = models.DateTimeField(null=True, blank=True)
    mastered_at       = models.DateTimeField(null=True, blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "word")
```

#### learning / Article & Quiz

```python
class Article(models.Model):
    user                  = models.ForeignKey(User, on_delete=models.CASCADE, related_name="articles")
    word_bank             = models.ForeignKey(WordBank, on_delete=models.SET_NULL, null=True)
    title                 = models.CharField(max_length=256)
    content_html          = models.TextField()                     # 带高亮标记的 HTML
    target_word_ids       = models.JSONField()                     # 目标单词 ID 列表（学习+复习）
    mastered_word_ids     = models.JSONField(default=list)         # 已掌握单词 ID（浅色高亮）
    hit_word_ids          = models.JSONField()                     # AI 实际命中的单词 ID 列表
    interests             = models.ManyToManyField(Interest, blank=True)
    sentence_complexity   = models.IntegerField()
    generated_at          = models.DateTimeField(auto_now_add=True)
    is_regenerated        = models.BooleanField(default=False)     # 是否为重新生成

    class Meta:
        ordering = ["-generated_at"]


class Quiz(models.Model):
    article      = models.OneToOneField(Article, on_delete=models.CASCADE, related_name="quiz")
    questions    = models.JSONField()                              # AI 返回的题目 JSON
    user_answers = models.JSONField(null=True, blank=True)         # 用户作答 {0: "A", 1: "B", ...}
    score        = models.IntegerField(null=True, blank=True)
    is_skipped   = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
```

#### learning / Interest

```python
class Interest(models.Model):
    name = models.CharField(max_length=64, unique=True)
    slug = models.SlugField(max_length=64, unique=True)

    def __str__(self):
        return self.name
```

#### learning / DailyUsage & LearningActivity

```python
class DailyUsage(models.Model):
    """跟踪每日文章生成次数"""
    user             = models.ForeignKey(User, on_delete=models.CASCADE)
    date             = models.DateField()
    generation_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "date")


class LearningActivity(models.Model):
    """学习活动记录 — 用于热力图和统计"""
    user              = models.ForeignKey(User, on_delete=models.CASCADE)
    date              = models.DateField()
    articles_read     = models.IntegerField(default=0)
    quizzes_completed = models.IntegerField(default=0)
    words_mastered    = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "date")
```

### 4.3 数据关系总结

| 关系 | 类型 | 说明 |
|------|------|------|
| WordBank → Word | 1:N | 一个词库包含多个单词 |
| User → UserWordStatus | 1:N | 每个用户对每个单词有一份独立状态 |
| Word → UserWordStatus | 1:N | 一个单词可被多个用户学习 |
| User → Article | 1:N | 一个用户有多篇文章 |
| Article → Quiz | 1:1 | 一篇文章对应一套测验 |
| User → Interest | M:N | 用户选择多个兴趣方向 |
| Article → Interest | M:N | 文章关联多个兴趣方向 |

---

## 5. AI 集成设计

### 5.1 DeepSeek API 调用

使用 OpenAI 兼容的 SDK 调用 DeepSeek（DeepSeek API 与 OpenAI SDK 兼容）：

```python
# learning/ai.py

from openai import OpenAI

client = OpenAI(
    api_key="sk-xxx",            # 从 config 读取
    base_url="https://api.deepseek.com",
)
```

### 5.2 调用策略

**两次独立调用**（D-14）：

```
请求 → DeepSeek API Call 1: 生成文章
     │
     ├── 成功 → DeepSeek API Call 2: 生成测验
     │              │
     │              ├── 成功 → 返回 {article, quiz}
     │              └── 失败 → 返回 {article, quiz: null}  (测验放弃)
     │
     └── 失败 → 返回错误，提示用户稍后重试 (D-43)
```

- 解析失败不做重试（D-16）
- 测验生成失败时文章仍可用

### 5.3 Prompt 设计

#### Call 1: 文章生成

```
System: You are an English article writer for language learners. Write engaging,
natural articles that incorporate target vocabulary words seamlessly.

User:
Write an article in English with the following requirements:
- Topic/Interest: {interests}
- Target word count: ~{word_count} words
- Sentence complexity level: {complexity}/9 (1=very simple, 9=native-level complex)
- Target vocabulary words to include (try to use as many as possible, minimum {min_words}):

{word_list}

Return your response as a JSON object:
{
  "title": "article title",
  "content": "full article text with paragraphs separated by \\n\\n",
  "hit_words": ["word1", "word2", ...],  // words from the list that appear in the article
  "glossary": {
    "word1": "definition in context",
    "word2": "definition in context"
  }
}

The article should flow naturally. Do NOT force every word in — quality over quantity.
```

#### Call 2: 测验生成

```
System: You are an English test creator. Create reading comprehension questions
based on the provided article.

User:
Based on the following article, create 5 multiple-choice quiz questions.

Article title: {title}
Article content: {content}

Requirements:
- Each question has 4 options (A/B/C/D), only one correct answer
- Questions should test reading comprehension, not vocabulary memorization
- Include the evidence (quote/excerpt) from the article for each correct answer

Return your response as a JSON object:
{
  "questions": [
    {
      "id": 1,
      "question": "question text",
      "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
      "correct": "A",
      "explanation": "explanation with evidence from the article"
    },
    ...
  ]
}
```

### 5.4 单词选取逻辑

```python
# learning/services.py

def select_words_for_article(user, word_bank, max_words=500):
    """
    从用户待学词中选取单词提供给 AI。
    包含：学习中的单词 + 待复习的单词
    超过 max_words 则随机抽取。
    """
    learning_words = UserWordStatus.objects.filter(
        user=user,
        word__word_bank=word_bank,
        status__in=[UserWordStatus.Status.LEARNING, UserWordStatus.Status.NEW],
    ).select_related("word")

    review_words = UserWordStatus.objects.filter(
        user=user,
        word__word_bank=word_bank,
        status=UserWordStatus.Status.REVIEW,
    ).select_related("word")

    word_pool = list(learning_words) + list(review_words)

    if len(word_pool) > max_words:
        import random
        word_pool = random.sample(word_pool, max_words)

    return word_pool
```

> 已掌握单词不放入 AI 单词池（D-12）。AI 仍可在文章中自然使用已掌握单词，前端以浅色高亮展示。

---

## 6. 核心流程设计

### 6.1 文章生成流程

```
用户点击 "Generate Article"
    │
    ▼
1. check_daily_limit(user)               → 超过每日上限？→ 拒绝
    │
    ▼
2. select_words_for_article(user, bank)  → 获取单词池
    │
    ▼
3. generate_article(words, interests, complexity)  → Call DeepSeek API
    │
    ├─ 失败 → 显示 "API 故障，请稍后重试"
    │
    ▼ 成功
4. parse article JSON → 验证格式
    │
    ├─ 格式错误 → 放弃，显示错误
    │
    ▼
5. save Article to DB
    │
    ▼
6. generate_quiz(article)                → Call DeepSeek API (第二次)
    │
    ├─ 失败/格式错误 → 保存 Article, quiz=null
    │
    ▼ 成功
7. save Quiz to DB
    │
    ▼
8. render article.html                   → 展示文章 + 测验
```

### 6.2 文章高亮渲染

```python
# learning/services.py

def build_highlighted_html(content: str, target_words: list[str], mastered_words: list[str]) -> str:
    """
    在文章 HTML 中：
    - 目标单词 → <strong class="word-target">word</strong>
    - 已掌握单词 → <span class="word-mastered">word</span>
    """
    # 遍历 content，对匹配的单词包裹对应标签
    # 注意：仅匹配完整单词（word boundary），避免子串误匹配
    ...
```

CSS:
```css
.word-target   { font-weight: bold; background: #fde68a; }  /* 醒目黄色 */
.word-mastered { background: #e5e7eb; color: #6b7280; }     /* 浅灰色 */
```

### 6.3 测验提交流程

```
用户提交答案
    │
    ▼
1. 解析表单 → {0: "A", 1: "B", 2: "C", 3: "A", 4: "D"}
    │
    ▼
2. 与 Quiz.questions[n].correct 对比 → 计算 score
    │
    ▼
3. 保存 Quiz.user_answers, Quiz.score
    │
    ▼
4. 逐题展示：正确/错误 + 解析
```

### 6.4 单词去留流程

```
用户完成阅读/测验后 → 进入 word_review 页面
    │
    ▼
展示所有 hit_words（AI 命中的目标单词列表）
每个单词旁有 [继续学习] [已掌握] 按钮
顶部有 "全部掌握" 批量按钮
    │
    ▼
用户逐个或批量操作
    │
    ├─ [继续学习] → UserWordStatus.status = "learning" (不变)
    │
    └─ [已掌握]   → UserWordStatus.status = "mastered"
                    UserWordStatus.mastered_at = now
                    schedule_review(status)     → 设置初始间隔 1 天
```

### 6.5 历史文章清理

```python
# learning/services.py

def cleanup_old_articles(user, max_articles=24):
    """
    保留最近 N 篇文章，删除超出的旧记录（D-46）。
    可在每次生成文章时调用。
    """
    articles = Article.objects.filter(user=user).order_by("-generated_at")
    if articles.count() > max_articles:
        ids_to_keep = articles.values_list("id", flat=True)[:max_articles]
        Article.objects.filter(user=user).exclude(id__in=ids_to_keep).delete()
```

---

## 7. URL 路由设计

### 7.1 根路由

```python
# config/urls.py
urlpatterns = [
    path("admin/",   admin.site.urls),          # Django Admin 后台
    path("",         include("learning.urls")),  # 学习主页
    path("account/", include("accounts.urls")),  # 登录/个人信息
    path("bank/",    include("wordbank.urls")),  # 词库相关（如需前端）
]
```

### 7.2 路由表

| 路由 | 视图 | 说明 |
|------|------|------|
| `/` | `learning.views.index` | 首页：词库选择 + 兴趣 + 复杂度 + 生成按钮 |
| `/article/<id>/` | `learning.views.article` | 阅读文章 + 测验区 |
| `/article/<id>/quiz/submit/` | `learning.views.submit_quiz` | 提交测验答案 |
| `/article/<id>/words/` | `learning.views.word_review` | 单词去留管理 |
| `/article/<id>/words/save/` | `learning.views.save_word_decisions` | 保存单词去留结果 |
| `/article/<id>/regenerate/` | `learning.views.regenerate` | 重新生成文章 |
| `/history/` | `learning.views.history` | 学习历史列表 |
| `/history/<id>/` | `learning.views.article_detail` | 历史文章详情 |
| `/stats/` | `learning.views.stats` | 学习统计 + 热力图 |
| `/account/login/` | `accounts.views.login_view` | 登录 |
| `/account/logout/` | `accounts.views.logout_view` | 登出 |
| `/account/profile/` | `accounts.views.profile` | 个人信息编辑 |

> 所有视图均使用 Django `@login_required` 装饰器保护。

---

## 8. 模板设计

### 8.1 页面清单

| 模板 | 对应功能 | 关键元素 |
|------|----------|----------|
| `base.html` | 全局布局 | 导航栏、用户信息、CSS/JS 引入 |
| `index.html` | 学习入口 | 词库下拉、兴趣多选复选框、复杂度滑块、生成按钮 |
| `article.html` | 文章+测验 | 文章区（带高亮）、滚动到测验区、跳过按钮 |
| `word_review.html` | 单词去留 | 单词卡片列表、每个单词两个按钮、批量操作按钮 |
| `history.html` | 历史记录 | 文章列表（标题、日期、单词数）、分页 |
| `stats.html` | 统计面板 | 热力图、累计统计数字 |
| `login.html` | 登录 | 用户名/密码表单 |
| `profile.html` | 个人信息 | 昵称、英语水平、学习目标 |

### 8.2 页面流转

```
login.html ──→ index.html ──→ article.html ──→ word_review.html
                   │                │               │
                   │                │ (跳过测验)     │ 提交后
                   │                └───────────────→ word_review.html
                   │
                   ├──→ history.html ──→ article.html (只读回顾)
                   └──→ stats.html
```

### 8.3 前端交互 (JavaScript)

仅少量增强，不需要框架：

- **复杂度滑块**：拖动时实时显示数值
- **测验提交**：表单提交后展示对错（可无 JS 纯表单实现）
- **批量操作**：勾选/全选 + 批量标记按钮
- **热力图**：使用内联 SVG 或简单 CSS grid 绘制

---

## 9. 配置设计

### 9.1 配置文件 `config/app_config.json`

```json
{
  "deepseek": {
    "api_key": "sk-xxxxxxxx",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "timeout_seconds": 60
  },
  "article": {
    "target_word_count": 500,
    "min_hit_words": 25,
    "max_hit_words": 50,
    "max_word_pool_size": 500
  },
  "limits": {
    "daily_generation_limit": 3,
    "article_history_retention": 24
  },
  "spaced_repetition": {
    "intervals": [1, 3, 7, 21, 60]
  }
}
```

### 9.2 配置加载

```python
# utils/config.py
import json
from pathlib import Path
from functools import lru_cache

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "app_config.json"

@lru_cache(maxsize=1)
def load_config() -> dict:
    """读取并缓存配置，服务启动后生效，修改需重启（D-42）"""
    with open(CONFIG_PATH) as f:
        return json.load(f)

def get_config(key: str, default=None):
    """通过点号分隔路径获取配置，如 get_config('article.target_word_count')"""
    cfg = load_config()
    for part in key.split("."):
        cfg = cfg.get(part, {})
    return cfg or default
```

> Admin 通过 Django Admin 后台编辑 `app_config.json` 文件（AD-04），修改后重启服务生效（D-42）。

---

## 10. 部署架构

### 10.1 服务器部署

```
┌─────────────────────────────────────────┐
│         Ubuntu Server (内网)             │
│                                         │
│  systemd                                │
│    └── gunicorn                         │
│          └── Django (SQLite + 静态文件)   │
│                │                        │
│                ├── SQLite DB 文件        │
│                ├── app_config.json      │
│                └── static/              │
│                                         │
│  用户通过 http://<server-ip>:8000 访问    │
└─────────────────────────────────────────┘
```

### 10.2 部署步骤概要

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 初始化数据库
python manage.py migrate

# 3. 创建 admin 用户
python manage.py createsuperuser

# 4. 预置兴趣类别
python manage.py loaddata initial_interests.json

# 5. 导入初始词库
python manage.py import_wordbank --name "上海高考" --csv data/sh_gaokao.csv

# 6. 收集静态文件
python manage.py collectstatic

# 7. 启动 (开发测试)
python manage.py runserver 0.0.0.0:8000

# 8. 生产部署
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2
```

### 10.3 systemd 服务单元

```ini
# /etc/systemd/system/wordlearner.service
[Unit]
Description=Word Learner Django App
After=network.target

[Service]
User=app
WorkingDirectory=/opt/wordlearner
ExecStart=/opt/wordlearner/venv/bin/gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 11. 安全设计

| 项 | 措施 |
|------|------|
| 用户认证 | Django `django.contrib.auth`，Session-based |
| 密码存储 | Django 默认 PBKDF2 哈希（`django.contrib.auth.hashers`） |
| 登录保护 | 全站 `@login_required`（除登录页） |
| CSRF | Django 内置 CSRF 中间件，所有 POST 表单受保护 |
| XSS | Django Templates 默认自动 HTML 转义 |
| SQL 注入 | Django ORM 参数化查询，无原始 SQL |
| API Key | 存储于服务器本地 JSON 文件，不暴露前端 |
| 静态文件 | Django `collectstatic` → 统一静态目录 |
| 会话安全 | `SESSION_COOKIE_HTTPONLY = True`, `SESSION_COOKIE_SECURE = False` (内网 HTTP) |
| 部署 | 仅监听内网 IP（`--bind 0.0.0.0` 对内网 OK），不暴露公网 |

---

## 12. 间隔重复算法

### 12.1 SM-2 简化版实现

```python
# learning/services.py
from datetime import datetime, timedelta, timezone

INTERVALS = [1, 3, 7, 21, 60]  # 递增间隔（天）(D-09)


def schedule_review(word_status: UserWordStatus) -> None:
    """
    单词标记为已掌握时调用。
    设置初始复习间隔为第 1 级（1 天后）。
    """
    word_status.status = UserWordStatus.Status.MASTERED
    word_status.mastered_at = datetime.now(timezone.utc)
    word_status.review_interval = INTERVALS[0]  # 1 天
    word_status.next_review_at = word_status.mastered_at + timedelta(days=INTERVALS[0])
    word_status.save()


def process_due_reviews() -> None:
    """
    定时任务：将到期复习的已掌握单词移入 review 状态。
    
    建议每天运行一次（通过 Django management command + cron）：
        python manage.py process_reviews
    """
    now = datetime.now(timezone.utc)
    due = UserWordStatus.objects.filter(
        status=UserWordStatus.Status.MASTERED,
        next_review_at__lte=now,
    )

    for status in due:
        status.status = UserWordStatus.Status.REVIEW
        status.save()
        # 该单词将出现在下次文章生成的单词池中 (C-12)


def advance_review_interval(word_status: UserWordStatus) -> None:
    """
    复习后推进到下一间隔。
    当包含该复习单词的文章被学习后调用。
    """
    current_idx = INTERVALS.index(word_status.review_interval) if word_status.review_interval in INTERVALS else 0
    next_idx = min(current_idx + 1, len(INTERVALS) - 1)
    word_status.review_interval = INTERVALS[next_idx]
    word_status.next_review_at = datetime.now(timezone.utc) + timedelta(days=INTERVALS[next_idx])
    word_status.last_reviewed_at = datetime.now(timezone.utc)
    word_status.save()
```

### 12.2 复习流程

```
[已掌握] ──(间隔到期)──→ [待复习]
                              │
                              │ 进入下次文章生成的单词池
                              │ AI 在文章中融入该单词
                              ▼
                         用户在新文章中看到该单词
                              │
                              │ 完成后推进间隔 (1→3→7→21→60)
                              ▼
                         [已掌握] (下一个间隔)
```

> 复习失败的场景暂不处理（C-13）。

---

## 附录 A: `requirements.txt`

```
Django>=5.1,<6.0
openai>=1.0,<2.0          # DeepSeek API 兼容 OpenAI SDK
gunicorn>=22.0
```

## 附录 B: Django Admin 注册项

| Admin 注册 | 说明 |
|------------|------|
| `User` + `Profile` (inline) | 用户管理（AD-01） |
| `WordBank` | 词库管理 |
| `Word` (inline in WordBank) | 单词 CRUD（AD-03） |
| `UserWordStatus` | 查看用户学习状态 |
| `Article` | 查看文章 |
| `Interest` | 兴趣类别管理 |
| 自定义 Admin View | CSV 导入（AD-02）、配置编辑（AD-04）、用户统计（AD-05） |

> Django 内置 Admin 覆盖了 AD-01、AD-03 的大部分需求。AD-02（CSV 导入）和 AD-04（配置编辑）通过 Admin 自定义 View 实现。

---

## 附录 C: v1.1 更新记录

以下功能在实现阶段新增或调整，与 v1.0 设计文档的差异：

| 变更 | 说明 |
|------|------|
| **Word Banks 用户端页面** | `/bank/` 新增词库列表、浏览、CSV 导入/导出、单词编辑弹窗 |
| **单词状态列** | Word Banks 浏览页面显示每个单词的 New/Learning/Review/Mastered 状态标签 |
| **直接标记已掌握** | Word Banks 页面支持一键将单词标记为 Mastered，无需通过文章流程 |
| **词库记忆** | Profile 新增 `selected_word_bank_id`，用户上次选择的词库自动预选 |
| **新用户单词初始化** | `_ensure_user_word_statuses()` 自动为新用户创建所有单词的 "new" 状态记录 |
| **兴趣类别扩展** | 从 10 个增至 13 个：新增 Sci-Fi、Mystery & Suspense、Crime & Detective |
| **响应式设计** | CSS 覆盖 3 个断点：iPad (≤1024px)、iPhone (≤768px)、小屏 (≤430px) |
| **暗色模式单词高亮** | `.word-target` / `.word-mastered` 自动适配 `prefers-color-scheme: dark` 和 `data-theme="dark"` |
| **CSV 导入放宽** | 定义列可为空（适配从 .doc 提取的无释义单词） |
| **is_phrase 清理** | 仅空格/连字符复合词标记为 phrase，单单词自动清除 |
| **上海高考词库** | 从 sh_gaokao.doc 提取 2,869 个单词导入，含中文释义 |

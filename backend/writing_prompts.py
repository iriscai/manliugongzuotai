"""Shared writing voice: direct narration, attribution only where it matters."""
import re

POLICY_VERSION = 'comic_title64_v4'
LEGACY_OPENING = '你正在把经过提炼和来源核对的素材改写成短篇漫画文章。'
LEGACY_RULE = LEGACY_OPENING + (
    '围绕一个重点重新组织，不能只换同义词或人物职业；不可虚构现实事件的关键事实、原话或结果。'
    '保持人物关系、数字用途、支付/处理状态和先后顺序。体裁随素材与本篇角度决定，不强制科普或搞笑。'
    '先形成连贯short_text作为审核副本，再将实际发布内容拆入分镜。'
    '发布标题+图内对白/旁白/标签+文尾附文/声明合计不超过300个非空白Unicode字符，最终图片不超过10张，独立封面也计入；'
    '不凑图，文尾默认不重复贴全文。标题准确且不误导，结尾自然收束，不补说教。'
    '每张分镜写信息任务、人物场景、动作、准确文字及生图提示词；本步骤不声称实际出图。'
    '无法满足来源或事实要求时明确问题，不硬交成稿。'
)
COMMON_OPENING = '你正在以素材正文、提炼元素和所属赛道创作中文短文成品。'
POLICY_OPENING = '本赛道来源表达：'
NEWS_CATEGORIES = frozenset({'国际', '军事', '时政社会'})
KNOWLEDGE_CATEGORIES = frozenset({'财经', '法律', '健康', '养老', '房产', '科学科技', '科普', '三农', '育儿', '运动健身'})

DIRECT_RULE_V1 = COMMON_OPENING + (
    '围绕本组主题重新安排信息、场景和表达，形成自然连贯的文章，不能只替换同义词或照搬原作的独有长句。'
    '默认直接叙述事件、展开观点或解释知识，不把文章写成对原文的介绍、摘录说明或读后报告。'
    '普通改写无需向读者交代借鉴过程，不添加“作者称”“据素材描述”“原文提到”“文中写道”“这篇文章告诉我们”等来源套话；'
    '资料链接、原文引用及提炼记录留在工具内部，不机械塞入成品；元素里的分析口吻不照抄进正文。'
    '用人物行为、具体细节、问题和必要因果承载内容，少用空泛评价，不在结尾补“没有答案”“有待核实”式流程话。'
    '保留支撑主题的人物关系、条件、顺序和关键结果，不编造现实事件的事实、当事人引语或结局，也不把来源经历冒充自己的亲历。'
    '标题准确且有吸引力，结尾自然，标题与文章合计不超过300个非空白Unicode字符。'
    '直接输出category、title、article三个JSON字段，不生成分镜、审核稿、评分或核实清单，不增加外部核实及反复评审步骤。'
)

COMIC_RULE_V2 = COMMON_OPENING + (
    '以本组主题为中心，提炼后重新组织内容，直接写成自然的文章，不写原文介绍或素材转述。'
    '标题先抓原标题的爆点：谁遇到了什么、具体动作、关键数字、冲突、反差或悬念。'
    '优先沿用原题的核心词、事实和吸引人的语序，只做删赘字、理顺口气及必要的本组角度调整，不能另换一个泛泛的大题目。'
    '原标题是长摘要时，取其中支撑本主题的核心句压缩，标题不超过64个字符；不要为了短而丢掉人物、事情或反差。'
    '多组选题各取原题与本组真正相关的爆点，不把其他组内容硬塞进来；原题夸张或无正文支持的部分改准确，保留真实看点。'
    '避免“背后的逻辑”“责任边界”“引人深思”“带来启示”等抽象标题，不把具体事件改成空泛评论。'
    '正文像跟熟人把一件事讲清楚，语气亲近、直白、顺口，多写短句和具体动作，少用书面套话、绕口长句和抽象议论。'
    '口语顺着内容自然出现，不每篇强塞同一口头禅，不靠堆语气词、夸大情绪或编造对白来装亲近。'
    '全文默认3至5个重点小节，简单素材2至3节即可，不凑段数。'
    '每节用【2至6字的内容型小标题】单独一行，接1至2句短正文，各节之间空一行；小标题要点明这一节具体讲什么。'
    '各节按事情推进或问题解释安排，一节只讲一个重点，能对应人物动作、场景、物件或可图解的差异，方便后续改成10张以内漫画。'
    '不要所有文章都套“起因、经过、反转、总结”，不写“第几幅、镜头、画面提示词”等制作说明，也不为漫画补造事实。'
    '篇幅以讲清重点为准，不为凑300字铺背景；删重复解释、无关枝节、空泛铺垫和末尾再总结，结尾自然停在结果、回应或明确重点。'
    '普通改写不添加“作者称”“据素材描述”“原文提到”“文中写道”等来源套话，不介绍借鉴过程。'
    '原文引用、链接和元素分析留在内部，不照抄进正文；重新组织表达，不照搬原作独有长句，也不把来源经历冒充本人亲历。'
    '人物关系、条件、数字用途、先后顺序和已知结果准确，不编造现实人物原话、事件结局或权威背书。'
    '标题、小节标题和正文合计不超过300个非空白Unicode字符，建议留出余量，不必写满。'
    '在本次生文中想清标题爆点和小节重点后，一次返回category、title、article三个JSON字段；'
    'article为带真实换行的完整分节正文，不输出Markdown代码块、提纲、分镜或审核说明，不新增模型评审或外部核实步骤。'
)

PARAGRAPH_RULE_V3 = COMIC_RULE_V2.replace(
    '全文默认3至5个重点小节，简单素材2至3节即可，不凑段数。',
    '正文必须写成8至15个自然段，总标题单独放在title字段，不计入正文段数。按实际叙事和信息量选择8至15段，不固定凑成同一段数。'
).replace(
    '每节用【2至6字的内容型小标题】单独一行，接1至2句短正文，各节之间空一行；小标题要点明这一节具体讲什么。',
    '只保留自然段正文，段与段之间空一行。每段不写主题、小标题、【标签】、序号或“第几段”，不要先写一个主题再解释。'
).replace(
    '各节按事情推进或问题解释安排，一节只讲一个重点，能对应人物动作、场景、物件或可图解的差异，方便后续改成10张以内漫画。',
    '每段对应后续一张图片的文案，整篇承接8至15张图。每段通常1句完整短句，必要时用简短对白，讲清一个动作、回应、信息变化或可图解的差异；相邻段要自然接续。'
    '只拆分已有的有效信息，不把一句话拆成半句话，不重复换词凑段数，不增加无依据的情节、对白或结论。'
).replace(
    '标题、小节标题和正文合计不超过300个非空白Unicode字符，建议留出余量，不必写满。',
    '标题和8至15段正文合计仍不超过300个非空白Unicode字符，段落要短而完整，留出余量，不必写满。'
).replace(
    '在本次生文中想清标题爆点和小节重点后，一次返回category、title、article三个JSON字段；',
    '在本次生文内想清标题爆点和8至15段的推进顺序，一次返回category、title、article三个JSON字段；'
).replace(
    'article为带真实换行的完整分节正文',
    'article为用空行分隔的8至15段完整正文，不带段落标题'
)

COMMON_RULE = PARAGRAPH_RULE_V3.replace(
    '优先沿用原题的核心词、事实和吸引人的语序，只做删赘字、理顺口气及必要的本组角度调整，不能另换一个泛泛的大题目。',
    '先以本条原始标题为基准，原标题在64字符以内且与本组选题一致时，尽量沿用，只做必要的顺口微调。'
    '需要调整时优先保留原题的核心词、人物、事件、关键数字、爆点和吸引人的语序，不另起一个泛泛的大题目。'
).replace(
    '原标题是长摘要时，取其中支撑本主题的核心句压缩，标题不超过64个字符；不要为了短而丢掉人物、事情或反差。',
    '作品标题不得超过64个Unicode字符，中文、字母、数字、标点和空格均计入长度。'
    '原标题超过64字符或是长摘要时，取其中支撑本主题的核心句压缩到64字符以内；保留主要人物、事件和反差，不改变原意。'
)


def source_policy(category):
    if category in NEWS_CATEGORIES:
        mode = (
            '本赛道通常涉及新闻和公共事件，按已有事实材料改写。清楚叙述已给出的事件、时间和进展；'
            '一方指控、单方宣称、战果说法、争议结论及统计数据，必须保留会影响读者判断的实际发言方、机构、时点和条件。'
            '用“某机构公布”“某方表示”等具体归属，名称只能取自输入，不能编造官方通报、媒体报道或已核实证明。'
            '客观经过不必句句加来源前缀，禁止用“据素材描述”笼统代替真实归属。'
        )
    elif category in KNOWLEDGE_CATEGORIES:
        mode = (
            '普通故事、生活观察和已有稳定知识直接写。涉及政策待遇、法规判决、投资数据、医疗疗效、研究发现或专业结论时，'
            '依输入保留必要的适用对象、条件、时间及真实机构或说法归属，不把个案写成普遍结论。'
            '不要为普通内容额外套“作者称”，也不要虚构研究、专家、法规或权威背书。'
        )
    else:
        mode = (
            '生活、情感、职场、育儿互动、作品解读等普通内容直接成文，按本主题写人、事、观点或办法，'
            '不先介绍原作者，不用“据素材描述”开篇，不反复提醒内容来自另一篇文章。'
            '作品解读可直接写作品名和角色名；真实采访或当事人原话确需引用时，保留实际说话人。'
        )
    return POLICY_OPENING + mode + (
        '普通匿名人物故事的日常矛盾不因此增加来源说明，直接以人物、事情、问题或观点起笔。'
        '归属是否必要还要看具体内容，不能只按分类贴标签；任何赛道涉及可识别现实人物的未证实指控、公共新闻或重要数据，'
        '都保留必要限定，不能把“某人声称”改写成已确认事实。输入未支持的扩展可以舍去，'
        '不得通过删来源改变事实性质。来源表达嵌入相关句子即可，不把整篇写成材料转述。'
    )


def writing_directions(rule):
    """Drop known shared wrappers, retaining category directions and custom text."""
    directions = []
    for paragraph in re.split(r'\n\s*\n', rule):
        if paragraph.startswith((LEGACY_OPENING, COMMON_OPENING, POLICY_OPENING)):
            continue
        kept = [line for line in paragraph.splitlines()
                if not line.startswith(('本行来源：', '已保存提炼结果：', '本篇角度：', '用户补充要求：'))]
        if any(line.strip() for line in kept):
            directions.append('\n'.join(kept))
    return '\n\n'.join(directions)


def upgrade_stock_rule(content, category):
    """Replace the recognized stock opening only; never overwrite custom prompts."""
    paragraphs = re.split(r'\n\s*\n', content, maxsplit=1)
    if paragraphs[0] not in (LEGACY_RULE,DIRECT_RULE_V1,COMIC_RULE_V2,PARAGRAPH_RULE_V3):
        return content
    remaining=paragraphs[1] if len(paragraphs)>1 else ''
    pieces=re.split(r'\n\s*\n',remaining,maxsplit=1)
    if pieces[0]==source_policy(category):remaining=pieces[1] if len(pieces)>1 else ''
    return COMMON_RULE + '\n\n' + source_policy(category) + '\n\n' + remaining


def migrate_stock_rules(c, timestamp):
    updated = 0
    for row in c.execute("SELECT id,category,content,revision FROM prompts WHERE kind='write'").fetchall():
        prompt_id, category, content, revision = tuple(row)
        new_content = upgrade_stock_rule(content, category)
        if new_content == content:
            continue
        c.execute('INSERT INTO prompt_history(prompt_id,content,revision,created_at) VALUES(?,?,?,?)',
                  (prompt_id, content, revision, timestamp))
        c.execute('UPDATE prompts SET content=?,revision=revision+1,updated_at=? WHERE id=?',
                  (new_content, timestamp, prompt_id))
        updated += 1
    return updated

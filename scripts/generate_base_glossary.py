#!/usr/bin/env python3
"""Build the bundled public base glossary from a reviewed allowlist."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "skill/assets/glossaries/base.json"


GENERAL = """
3d|3D
3 d|3D
iphone|iPhone
Iphone|iPhone
IPhone|iPhone
android|Android
wifi|Wi-Fi
WiFi|Wi-Fi
Wifi|Wi-Fi
wi-fi|Wi-Fi
WIFI|Wi-Fi
type-c|USB-C
typec|USB-C
Type C|USB-C
app store|App Store
App store|App Store
appstore|App Store
youtube|YouTube
Youtube|YouTube
you tube|YouTube
tiktok|TikTok
Tiktok|TikTok
Tik Tok|TikTok
instagram|Instagram
facebook|Facebook
wechat|WeChat
Wechat|WeChat
airdrop|AirDrop
Airdrop|AirDrop
v log|vlog
bgm|BGM
Bgm|BGM
hdr|HDR
4k|4K
4 k|4K
8k|8K
8 k|8K
gps|GPS
qr|QR
pdf|PDF
Pdf|PDF
url|URL
nfc|NFC
"""


CHINESE = """
按耐不住|按捺不住
迫不急待|迫不及待
一如继往|一如既往
甘败下风|甘拜下风
穿流不息|川流不息
暴珍天物|暴殄天物
名信片|明信片
重新在来|重新再来
不径而走|不胫而走
张灯节彩|张灯结彩
再接再励|再接再厉
默守成规|墨守成规
依些|一些
\u60c5\u6033|情况
搜已|所以
这哩|这里
\u600e\u569c|怎么
学姣|学校
\u4efc\u52a1|任务
愿赖|原来
兔然|突然
希冠|希望
眼靓|眼睛
联糸|联系
为什幺|为什么
哪理|哪里
哪哩|哪里
毎天|每天
桃论|讨论
\u62c5\u4efc|担任
音龠|音乐
厌力|压力
靣对|面对
庄况|状况
一糸列|一系列
寄怪|奇怪
岀发|出发
休葸|休息
\u5fb5\u7b11|微笑
陌光|阳光
悾怕|恐怕
打篹|打算
走岀|走出
怎么杨|怎么样
便谊|便宜
\u4fe1\u4efc|信任
骠了|漂亮
票凉|漂亮
漂凉|漂亮
夭空|天空
税觉|睡觉
付岀|付出
新家波|新加坡
新家坡|新加坡
澎涨|膨胀
剥歇|剥削
提昌|提倡
严悛|严峻
咳嗦|咳嗽
祟拜|崇拜
徙弟|徒弟
步阀|步伐
火者站|火车站
陪偿|赔偿
种要性|重要性
村庒|村庄
湖涂|糊涂
大搂|大楼
焟烛|蜡烛
火熖|火焰
包裏|包裹
剧夲|剧本
寰麟|婚礼
灯垄|灯笼
不好亿思|不好意思
名付其实|名副其实
擵擦|摩擦
\u5fac\u665a|傍晚
概慨|感慨
个中各样|各种各样
瞅天|秋天
饭莱|饭菜
往亊|往事
赚嫌|赚钱
沤吐|呕吐
赌搏|赌博
记念馆|纪念馆
庒稼|庄稼
按磨|按摩
沏澈|清澈
将学金|奖学金
繁洐|繁衍
扑实|朴实
小心奕奕|小心翼翼
通货澎胀|通货膨胀
燿眼|耀眼
泛烂|泛滥
充佩|充沛
修茸|修葺
红署|红薯
点视机|电视机
\u5537\u610f\u601d|有意思
迁徏|迁徙
\u4eb7\u4ef7|廉价
讷闷|纳闷
裸漏|裸露
鬼异|诡异
俱怕|惧怕
搅伴|搅拌
沉寝|沉浸
\u8636\u5ce8|巍峨
\u6793\u62f1|斗拱
堪湛|精湛
说不凊|说不清
塞太阳|晒太阳
背颂|背诵
哆唆|哆嗦
囗吻|口吻
怠漫|怠慢
大们口|大门口
简漏|简陋
酦酵|发酵
强焊|强悍
招慕|招募
手电桶|手电筒
\u6e29\u97fe|温馨
期刋|期刊
手摽|手表
疆绳|缰绳
渲器|喧嚣
晶螢|晶莹
蒸茏|蒸笼
巅覆|颠覆
歺桌|餐桌
绅仕|绅士
痲痹|麻痹
敝敞|宽敞
\u9661\u9657|陡峭
交相机|照相机
晚歺|晚餐
掂记|惦记
缠饶|缠绕
挽惜|惋惜
潮讽|嘲讽
暑名|署名
期肦|期盼
\u5055\u4e66|楷书
惊赅|惊骇
驾驿|驾驭
\u817c\u6000|缅怀
溃乏|匮乏
深髓|深邃
怆皇|仓皇
釆摘|采摘
絣干|饼干
向日蔡|向日葵
千涸|干涸
像征性|象征性
罂栗|罂粟
泥宁|泥泞
梆架|绑架
跷首|翘首
真缔|真谛
筹马|筹码
\u63ac\u8eac|鞠躬
迭荡|跌宕
烣烬|灰烬
脖胫|脖颈
合睦|和睦
十子路口|十字路口
隹节|佳节
煹火|篝火
\u7231\u771b|暧昧
暄闹|喧闹
拘紧|拘谨
\u60ca\u8c14|惊愕
稠怅|惆怅
浅溥|浅薄
\u5ba2\u500c|客官
架驶舱|驾驶舱
呑咽|吞咽
竟争者|竞争者
山嵴|山脊
撒骄|撒娇
荟粹|荟萃
\u6267\u602e|执拗
贫脊|贫瘠
桔杆|秸秆
\u8865\u976a|补丁
蹒姗|蹒跚
狐线|弧线
偏坦|偏袒
冷暧|冷暖
挠恕|饶恕
剌激性|刺激性
怎门办|怎么办
附瞰|俯瞰
簸萁|簸箕
拾缀|拾掇
原貎|原貌
佼洁|皎洁
风尘扑扑|风尘仆仆
竹蒿|竹篙
溜哒|溜达
虰咬|叮咬
秘藉|秘籍
无可耐何|无可奈何
彼比皆是|比比皆是
燃然一新|焕然一新
成出不穷|层出不穷
胆大忘为|胆大妄为
独树一枝|独树一帜
耀武杨威|耀武扬威
晃然大悟|恍然大悟
中流抵柱|中流砥柱
卧心尝胆|卧薪尝胆
各施其职|各司其职
此起披伏|此起彼伏
兴高彩列|兴高采烈
不可一势|不可一世
无影无终|无影无踪
乱七八槽|乱七八糟
名闻暇迩|名闻遐迩
星罗旗布|星罗棋布
错手不及|措手不及
坚定不疑|坚定不移
怒不可歇|怒不可遏
家寓户晓|家喻户晓
气喘嘘吁|气喘吁吁
无与论比|无与伦比
鬼鬼崇崇|鬼鬼祟祟
慎时度势|审时度势
发号司令|发号施令
心旷神饴|心旷神怡
喜出往外|喜出望外
非夷所思|匪夷所思
无计于事|无济于事
不言而语|不言而喻
决无仅有|绝无仅有
喧然大波|轩然大波
手足无错|手足无措
富丽堂黄|富丽堂皇
措踪复杂|错综复杂
伸东击西|声东击西
大声急呼|大声疾呼
拙咄逼人|咄咄逼人
同仇敌慨|同仇敌忾
斩钉接铁|斩钉截铁
责无旁代|责无旁贷
炉火纯清|炉火纯青
提心掉胆|提心吊胆
前朴后继|前仆后继
知之不理|置之不理
惊慌失错|惊慌失措
归跟结底|归根结底
一败糊地|一败涂地
坚持不榭|坚持不懈
大名顶顶|大名鼎鼎
污烟胀气|乌烟瘴气
走途无路|走投无路
络译不绝|络绎不绝
哑雀无声|鸦雀无声
眼花暸乱|眼花缭乱
汹涌彭湃|汹涌澎湃
诩栩如生|栩栩如生
漫不精心|漫不经心
有条不稳|有条不紊
天经地仪|天经地义
胡做非为|胡作非为
凶相必露|凶相毕露
犹予不决|犹豫不决
扬常而去|扬长而去
忘恩负意|忘恩负义
漠漠糊糊|模模糊糊
别出心才|别出心裁
一窃不通|一窍不通
廖寥无几|寥寥无几
不贻余力|不遗余力
事得其反|适得其反
不共带天|不共戴天
一视同人|一视同仁
五脏六俯|五脏六腑
谎谎张张|慌慌张张
魂不符体|魂不附体
绪序渐进|循序渐进
出类拔翠|出类拔萃
不寒而立|不寒而栗
一触既发|一触即发
团为一谈|混为一谈
首当其充|首当其冲
按居乐业|安居乐业
众目暌睽|众目睽睽
一思不苟|一丝不苟
安兵不动|按兵不动
\u864e\u89c6\u803d\u7708|虎视眈眈
以逸代劳|以逸待劳
义不容词|义不容辞
毅无反顾|义无反顾
处心集虑|处心积虑
一榻糊涂|一塌糊涂
心安礼得|心安理得
博大经深|博大精深
专心至志|专心致志
痛心嫉首|痛心疾首
无所是从|无所适从
推波助谰|推波助澜
循规韬矩|循规蹈矩
"""


def rows(block: str, category: str, reason: str) -> list[dict[str, str]]:
    result = []
    for line in block.strip().splitlines():
        wrong, right = (part.strip() for part in line.split("|", 1))
        result.append(
            {
                "text": wrong,
                "suggest": right,
                "reason": reason,
                "category": category,
            }
        )
    return result


def main() -> None:
    items = rows(GENERAL, "public-standard", "通用英文或产品标准写法")
    items += rows(CHINESE, "common-confusion", "常见错字或语音识别混淆，仅作校对建议")
    seen: set[str] = set()
    duplicates = []
    for item in items:
        if item["text"] in seen:
            duplicates.append(item["text"])
        seen.add(item["text"])
        if item["text"] == item["suggest"]:
            raise SystemExit(f'same source and suggestion: {item["text"]}')
    if duplicates:
        raise SystemExit(f"duplicate source terms: {duplicates}")
    if not 300 <= len(items) <= 400:
        raise SystemExit(f"base glossary must stay within 300-400 entries, got {len(items)}")
    payload = {
        "version": 1,
        "name": "通用基础词库",
        "sources": [
            {
                "name": "pycorrector",
                "url": "https://github.com/shibing624/pycorrector",
                "license": "Apache-2.0",
                "usage": "混淆集结构与 ASR 纠错设计参考",
            },
            {
                "name": "macro-correct",
                "url": "https://github.com/yongzhuo/macro-correct",
                "license": "Apache-2.0",
                "usage": "候选对照来源；未整库复制，已逐条筛选",
            },
        ],
        "forbidden_terms": items,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "entries": len(items)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Conservative, versioned administrative mapping; unknown text is never guessed."""

NORMALIZATION_VERSION = "cn-regions-2"
PROVINCES = (
    "北京",
    "天津",
    "河北",
    "山西",
    "内蒙古",
    "辽宁",
    "吉林",
    "黑龙江",
    "上海",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广东",
    "广西",
    "海南",
    "重庆",
    "四川",
    "贵州",
    "云南",
    "西藏",
    "陕西",
    "甘肃",
    "青海",
    "宁夏",
    "新疆",
    "台湾",
    "香港",
    "澳门",
)
CITIES = {
    "安徽": ("滁州",),
    "福建": ("福州", "厦门", "莆田", "三明", "泉州", "漳州", "南平", "龙岩", "宁德"),
    "广东": ("广州", "深圳"),
}
ALIASES: dict[str, str] = {"CN": "CN", "全国": "CN", "中国": "CN"}
for province in PROVINCES:
    code = "CN/" + province
    for alias in (province, province + "省", code, code + "省"):
        ALIASES[alias] = code
for municipality in ("北京", "天津", "上海", "重庆"):
    ALIASES[municipality + "市"] = "CN/" + municipality
for province, cities in CITIES.items():
    for city in cities:
        code = f"CN/{province}/{city}"
        for alias in (
            code,
            code + "市",
            f"CN/{province}省/{city}市",
            f"{province}/{city}",
            f"{province}省/{city}市",
            f"{province}省{city}市",
            city,
            city + "市",
        ):
            ALIASES[alias] = code
for name, code in (
    ("内蒙古自治区", "CN/内蒙古"),
    ("广西壮族自治区", "CN/广西"),
    ("西藏自治区", "CN/西藏"),
    ("宁夏回族自治区", "CN/宁夏"),
    ("新疆维吾尔自治区", "CN/新疆"),
    ("香港特别行政区", "CN/香港"),
    ("澳门特别行政区", "CN/澳门"),
):
    ALIASES[name] = code


def normalize_region(value: str) -> str:
    if not isinstance(value, str) or value.strip() not in ALIASES:
        raise ValueError("REGION_UNMAPPED: context requires a supported administrative region")
    return ALIASES[value.strip()]

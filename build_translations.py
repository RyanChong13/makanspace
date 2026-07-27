"""
Generate .po files and compile to .mo for zh_Hans, ta, ms.
Run: python build_translations.py
"""
import os
from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
from babel.messages.pofile import write_po

BASE = os.path.dirname(os.path.abspath(__file__))

# All translatable strings extracted from templates
TRANSLATIONS = {
    "zh_Hans": {
        # Header
        "Log In": "登录",
        "Log Out": "退出",
        "Register Company": "注册公司",
        "Post Stall": "发布摊位",
        # Listing list
        "Browse Hawker Stalls": "浏览小贩摊位",
        "Hawker Stalls for Rent": "出租小贩摊位",
        "List": "列表",
        "Map": "地图",
        "Featured first": "精选优先",
        "Newest": "最新",
        "Price: Low to High": "价格：从低到高",
        "Price: High to Low": "价格：从高到低",
        # Filter panel
        "Cost Range (SGD/month)": "租金范围（新元/月）",
        "Size": "面积",
        "Lease Duration": "租期",
        "Any duration": "不限租期",
        "Less than 6 months": "少于6个月",
        "6 to 12 months": "6到12个月",
        "1 to 2 years": "1到2年",
        "More than 2 years": "超过2年",
        "MRT/Bus Distance": "地铁/巴士距离",
        "Any distance": "不限距离",
        "Within 5 min walk": "步行5分钟内",
        "Within 10 min walk": "步行10分钟内",
        "Within 15 min walk": "步行15分钟内",
        "Amenities": "设施",
        "Has Grease Trap": "有油脂拦截器",
        "Clear all filters": "清除所有筛选",
        # Listing card
        "Business verified": "已验证商家",
        "Verified": "已验证",
        "FEATURED": "精选",
        "Grease trap": "油脂拦截器",
        "more": "更多",
        "Apply Now": "立即申请",
        # Listing detail
        "Back to listings": "返回列表",
        "Account Settings": "账户设置",
        "Verified Landlord": "已验证房东",
        "Listing code": "编号",
        "Postal Code": "邮政编码",
        "Nearest MRT/Bus": "最近地铁/巴士",
        "F&B Operational Costs": "餐饮运营成本",
        "Grease Trap Fee": "油脂拦截器费用",
        "Dishwashing Cost": "洗碗费用",
        "Est. Daily Footfall": "预估每日客流量",
        "Description": "描述",
        "Available Tasting / Viewing Slots": "可用品尝/参观时段",
        "Edit Listing": "编辑列表",
        "View Applications": "查看申请",
        "Manage Tasting Slots": "管理品尝时段",
        "Boost this Listing": "推广此列表",
        # Listing create
        "Post a Hawker Stall": "发布小贩摊位",
        "Post Your Hawker Stall": "发布您的小贩摊位",
        "Fill in your stall details. Your listing will be reviewed by our team before going live.": "填写摊位详情。我们的团队会在上线前审核您的列表。",
        "Please correct the errors below.": "请更正以下错误。",
        "Stall Title": "摊位名称",
        "Monthly Rent (SGD)": "月租金（新元）",
        "Max Rent (optional)": "最高租金（可选）",
        "Size (sqft)": "面积（平方英尺）",
        "WhatsApp Contact Number": "WhatsApp联系电话",
        "F&B Operational Costs (optional)": "餐饮运营成本（可选）",
        "Photos (up to 6)": "照片（最多6张）",
        # Results
        "stall": "个摊位",
        "found": "找到",
        "No stalls match your filters": "没有符合条件的摊位",
        "Try broadening your search or clearing some filters.": "请尝试扩大搜索范围或清除部分筛选条件。",
        # Footer
        "Connecting hawker stall owners with prospective hawkers across Singapore.": "连接新加坡各地小贩摊主与有意经营者。",
        "Connecting hawker companies with aspiring hawkers across Singapore. Only NEA-directly-tendered centres are excluded — private coffee shops, food courts, and appointed-operator hawker centres are welcome.": "连接新加坡的熟食公司与有志小贩。仅排除国家环境局直接招标的中心——私人咖啡店、美食广场和获委任运营商的小贩中心都欢迎。",
        # Company signup
        "Register Your Company": "注册您的公司",
        "Register as a corporate F&B landlord. Once verified by our admin team, you can invite leasing managers and create stall listings.": "注册为餐饮企业房东。经管理员验证后，您可以邀请租赁经理并创建摊位列表。",
        "Company Legal Name": "公司法定名称",
        "UEN (Business Registration)": "UEN（商业注册）",
        "Primary Region": "主要区域",
        "Business Registration Document": "商业注册文件",
        "Your Account (First Leasing Manager)": "您的账户（首位租赁经理）",
        "Your Email": "您的邮箱",
        "First Name": "名字",
        "Last Name": "姓氏",
        "Phone Number": "电话号码",
        "Password": "密码",
        "Already have an account?": "已有账户？",
        "Log in": "登录",
    },
    "ta": {
        # Header
        "Log In": "உள்நுழை",
        "Log Out": "வெளியேறு",
        "Register Company": "நிறுவனத்தை பதிவு செய்",
        "Post Stall": "கடை பதிவிடு",
        # Listing list
        "Browse Hawker Stalls": "ஹாக்கர் கடைகளை உலாவு",
        "Hawker Stalls for Rent": "வாடகைக்கு ஹாக்கர் கடைகள்",
        "List": "பட்டியல்",
        "Map": "வரைபடம்",
        "Featured first": "சிறப்பு முதலில்",
        "Newest": "புதியது",
        "Price: Low to High": "விலை: குறைவிலிருந்து அதிகம்",
        "Price: High to Low": "விலை: அதிகத்திலிருந்து குறைவு",
        # Filter panel
        "Cost Range (SGD/month)": "விலை வரம்பு (SGD/மாதம்)",
        "Size": "அளவு",
        "Lease Duration": "குத்தகை காலம்",
        "Any duration": "எந்த காலமும்",
        "Less than 6 months": "6 மாதங்களுக்கும் குறைவு",
        "6 to 12 months": "6 முதல் 12 மாதங்கள்",
        "1 to 2 years": "1 முதல் 2 ஆண்டுகள்",
        "More than 2 years": "2 ஆண்டுகளுக்கு மேல்",
        "MRT/Bus Distance": "MRT/பேருந்து தூரம்",
        "Any distance": "எந்த தூரமும்",
        "Within 5 min walk": "5 நிமிட நடைக்குள்",
        "Within 10 min walk": "10 நிமிட நடைக்குள்",
        "Within 15 min walk": "15 நிமிட நடைக்குள்",
        "Amenities": "வசதிகள்",
        "Has Grease Trap": "கொழுப்பு பொறி உள்ளது",
        "Clear all filters": "அனைத்து வடிகட்டிகளையும் அழி",
        # Listing card
        "Business verified": "வணிகம் சரிபார்க்கப்பட்டது",
        "Verified": "சரிபார்க்கப்பட்டது",
        "FEATURED": "சிறப்பு",
        "Grease trap": "கொழுப்பு பொறி",
        "more": "மேலும்",
        "Apply Now": "இப்போது விண்ணப்பி",
        # Listing detail
        "Back to listings": "பட்டியலுக்கு திரும்பு",
        "Account Settings": "கணக்கு அமைப்புகள்",
        "Verified Landlord": "சரிபார்க்கப்பட்ட நிலஉரிமையாளர்",
        "Listing code": "பட்டியல் குறியீடு",
        "Postal Code": "அஞ்சல் குறியீடு",
        "Nearest MRT/Bus": "அருகில் MRT/பேருந்து",
        "F&B Operational Costs": "உணவு மற்றும் பானம் செயல்பாட்டு செலவுகள்",
        "Grease Trap Fee": "கொழுப்பு பொறி கட்டணம்",
        "Dishwashing Cost": "பாத்திரம் கழுவும் செலவு",
        "Est. Daily Footfall": "மதிப்பிடப்பட்ட தினசரி காலடி",
        "Description": "விவரம்",
        "Available Tasting / Viewing Slots": "கிடைக்கும் சுவைப்பு / பார்வை நேரங்கள்",
        "Edit Listing": "பட்டியலைத் திருத்து",
        "View Applications": "விண்ணப்பங்களைப் பார்",
        "Manage Tasting Slots": "சுவைப்பு நேரங்களை நிர்வகி",
        "Boost this Listing": "இந்த பட்டியலை ஊக்குவி",
        # Listing create
        "Post a Hawker Stall": "ஹாக்கர் கடையை பதிவிடு",
        "Post Your Hawker Stall": "உங்கள் ஹாக்கர் கடையை பதிவிடுங்கள்",
        "Fill in your stall details. Your listing will be reviewed by our team before going live.": "உங்கள் கடை விவரங்களை நிரப்பவும். நேரலையாகும் முன் எங்கள் குழு மதிப்பாய்வு செய்யும்.",
        "Please correct the errors below.": "கீழே உள்ள பிழைகளை சரிசெய்யவும்.",
        "Stall Title": "கடை தலைப்பு",
        "Monthly Rent (SGD)": "மாத வாடகை (SGD)",
        "Max Rent (optional)": "அதிகபட்ச வாடகை (விருப்பம்)",
        "Size (sqft)": "அளவு (சதுர அடி)",
        "WhatsApp Contact Number": "WhatsApp தொடர்பு எண்",
        "F&B Operational Costs (optional)": "உணவு செயல்பாட்டு செலவுகள் (விருப்பம்)",
        "Photos (up to 6)": "படங்கள் (6 வரை)",
        # Results
        "stall": "கடை",
        "found": "காணப்பட்டது",
        "No stalls match your filters": "உங்கள் வடிகட்டிகளுக்கு பொருந்தும் கடைகள் இல்லை",
        "Try broadening your search or clearing some filters.": "தேடலை விரிவுபடுத்தவும் அல்லது சில வடிகட்டிகளை அழிக்கவும்.",
        # Footer
        "Connecting hawker stall owners with prospective hawkers across Singapore.": "சிங்கப்பூர் முழுவதும் ஹாக்கர் கடை உரிமையாளர்களை எதிர்கால ஹாக்கர்களுடன் இணைக்கிறது.",
        "Connecting hawker companies with aspiring hawkers across Singapore. Only NEA-directly-tendered centres are excluded — private coffee shops, food courts, and appointed-operator hawker centres are welcome.": "சிங்கப்பூர் முழுவதும் ஹாக்கர் நிறுவனங்களை எதிர்கால ஹாக்கர்களுடன் இணைக்கிறது. NEA நேரடியாக டெண்டர் வழங்கிய மையங்கள் மட்டும் விலக்கப்பட்டுள்ளன — தனியார் காபி கடைகள், உணவு மண்டபங்கள் மற்றும் நியமிக்கப்பட்ட இயக்குநர் ஹாக்கர் மையங்கள் வரவேற்கப்படுகின்றன.",
        # Company signup
        "Register Your Company": "உங்கள் நிறுவனத்தை பதிவு செய்யுங்கள்",
        "Register as a corporate F&B landlord. Once verified by our admin team, you can invite leasing managers and create stall listings.": "நிறுவன உணவு நிலஉரிமையாளராக பதிவு செய்யுங்கள். நிர்வாக குழுவால் சரிபார்க்கப்பட்ட பிறகு, குத்தகை மேலாளர்களை அழைத்து கடை பட்டியல்களை உருவாக்கலாம்.",
        "Company Legal Name": "நிறுவன சட்டபூர்வ பெயர்",
        "UEN (Business Registration)": "UEN (வணிக பதிவு)",
        "Primary Region": "முதன்மை பகுதி",
        "Business Registration Document": "வணிக பதிவு ஆவணம்",
        "Your Account (First Leasing Manager)": "உங்கள் கணக்கு (முதல் குத்தகை மேலாளர்)",
        "Your Email": "உங்கள் மின்னஞ்சல்",
        "First Name": "முதல் பெயர்",
        "Last Name": "குடும்பப் பெயர்",
        "Phone Number": "தொலைபேசி எண்",
        "Password": "கடவுச்சொல்",
        "Already have an account?": "ஏற்கனவே கணக்கு உள்ளதா?",
        "Log in": "உள்நுழை",
    },
    "ms": {
        # Header
        "Log In": "Log Masuk",
        "Log Out": "Log Keluar",
        "Register Company": "Daftar Syarikat",
        "Post Stall": "Siarkan Gerai",
        # Listing list
        "Browse Hawker Stalls": "Layari Gerai Penjaja",
        "Hawker Stalls for Rent": "Gerai Penjaja Untuk Disewa",
        "List": "Senarai",
        "Map": "Peta",
        "Featured first": "Tetapan pertama",
        "Newest": "Terbaru",
        "Price: Low to High": "Harga: Rendah ke Tinggi",
        "Price: High to Low": "Harga: Tinggi ke Rendah",
        # Filter panel
        "Cost Range (SGD/month)": "Julat Kos (SGD/bulan)",
        "Size": "Saiz",
        "Lease Duration": "Tempoh Sewa",
        "Any duration": "Sebarang tempoh",
        "Less than 6 months": "Kurang dari 6 bulan",
        "6 to 12 months": "6 hingga 12 bulan",
        "1 to 2 years": "1 hingga 2 tahun",
        "More than 2 years": "Lebih dari 2 tahun",
        "MRT/Bus Distance": "Jarak MRT/Bas",
        "Any distance": "Sebarang jarak",
        "Within 5 min walk": "Dalam 5 minit berjalan",
        "Within 10 min walk": "Dalam 10 minit berjalan",
        "Within 15 min walk": "Dalam 15 minit berjalan",
        "Amenities": "Kemudahan",
        "Has Grease Trap": "Ada Perangkap Gris",
        "Clear all filters": "Kosongkan semua penapis",
        # Listing card
        "Business verified": "Perniagaan disahkan",
        "Verified": "Disahkan",
        "FEATURED": "TETAPAN",
        "Grease trap": "Perangkap gris",
        "more": "lagi",
        "Apply Now": "Mohon Sekarang",
        # Listing detail
        "Back to listings": "Kembali ke senarai",
        "Account Settings": "Tetapan Akaun",
        "Verified Landlord": "Tuan Tanah Disahkan",
        "Listing code": "Kod senarai",
        "Postal Code": "Poskod",
        "Nearest MRT/Bus": "MRT/Bas Terdekat",
        "F&B Operational Costs": "Kos Operasi F&B",
        "Grease Trap Fee": "Yuran Perangkap Gris",
        "Dishwashing Cost": "Kos Basuh Pinggan",
        "Est. Daily Footfall": "Anggaran Trafik Harian",
        "Description": "Penerangan",
        "Available Tasting / Viewing Slots": "Slot Merasa / Melihat yang Tersedia",
        "Edit Listing": "Sunting Senarai",
        "View Applications": "Lihat Permohonan",
        "Manage Tasting Slots": "Urus Slot Merasa",
        "Boost this Listing": "Galakkan Senarai Ini",
        # Listing create
        "Post a Hawker Stall": "Siarkan Gerai Penjaja",
        "Post Your Hawker Stall": "Siarkan Gerai Penjaja Anda",
        "Fill in your stall details. Your listing will be reviewed by our team before going live.": "Isikan butiran gerai anda. Senarai anda akan disemak oleh pasukan kami sebelum disiarkan.",
        "Please correct the errors below.": "Sila betulkan kesilapan di bawah.",
        "Stall Title": "Tajuk Gerai",
        "Monthly Rent (SGD)": "Sewa Bulanan (SGD)",
        "Max Rent (optional)": "Sewa Maksimum (pilihan)",
        "Size (sqft)": "Saiz (kaki persegi)",
        "WhatsApp Contact Number": "Nombor Hubungan WhatsApp",
        "F&B Operational Costs (optional)": "Kos Operasi F&B (pilihan)",
        "Photos (up to 6)": "Foto (sehingga 6)",
        # Results
        "stall": "gerai",
        "found": "dijumpai",
        "No stalls match your filters": "Tiada gerai yang sepadan dengan penapis anda",
        "Try broadening your search or clearing some filters.": "Cuba luaskan carian anda atau kosongkan beberapa penapis.",
        # Footer
        "Connecting hawker stall owners with prospective hawkers across Singapore.": "Menghubungkan pemilik gerai penjaja dengan penjaja berpotensi di seluruh Singapura.",
        "Connecting hawker companies with aspiring hawkers across Singapore. Only NEA-directly-tendered centres are excluded — private coffee shops, food courts, and appointed-operator hawker centres are welcome.": "Menghubungkan syarikat penjaja dengan penjaja berpotensi di seluruh Singapura. Hanya pusat yang ditender secara langsung oleh NEA dikecualikan — kedai kopi persendirian, food court, dan pusat penjaja pengendali dilantik dialu-alukan.",
        # Company signup
        "Register Your Company": "Daftar Syarikat Anda",
        "Register as a corporate F&B landlord. Once verified by our admin team, you can invite leasing managers and create stall listings.": "Daftar sebagai tuan tanah F&B korporat. Setelah disahkan oleh pasukan pentadbir, anda boleh menjemput pengurus pajakan dan membuat senarai gerai.",
        "Company Legal Name": "Nama Undang-undang Syarikat",
        "UEN (Business Registration)": "UEN (Pendaftaran Perniagaan)",
        "Primary Region": "Rantau Utama",
        "Business Registration Document": "Dokumen Pendaftaran Perniagaan",
        "Your Account (First Leasing Manager)": "Akaun Anda (Pengurus Pajakan Pertama)",
        "Your Email": "E-mel Anda",
        "First Name": "Nama Pertama",
        "Last Name": "Nama Akhir",
        "Phone Number": "Nombor Telefon",
        "Password": "Kata Laluan",
        "Already have an account?": "Sudah mempunyai akaun?",
        "Log in": "Log masuk",
    },
}

LANG_META = {
    "zh_Hans": {"language": "zh_Hans", "language_team": "Chinese (Simplified)", "project": "MakanSpace"},
    "ta": {"language": "ta", "language_team": "Tamil", "project": "MakanSpace"},
    "ms": {"language": "ms", "language_team": "Malay", "project": "MakanSpace"},
}


def build():
    for lang, strings in TRANSLATIONS.items():
        meta = LANG_META[lang]
        cat = Catalog(
            locale=meta["language"],
            project=meta["project"],
            domain="django",
        )
        for msgid, msgstr in strings.items():
            cat.add(msgid, msgstr)

        # Write .po
        po_dir = os.path.join(BASE, "locale", lang, "LC_MESSAGES")
        os.makedirs(po_dir, exist_ok=True)
        po_path = os.path.join(po_dir, "django.po")
        mo_path = os.path.join(po_dir, "django.mo")

        with open(po_path, "wb") as f:
            write_po(f, cat, sort_output=True)

        # Compile to .mo
        with open(mo_path, "wb") as f:
            write_mo(f, cat)

        print(f"  {lang}: {len(strings)} strings -> {po_path} + {mo_path}")

    print("\nDone! All translations compiled.")


if __name__ == "__main__":
    build()

# تسليم خدمة الذكاء الاصطناعي — VibeLocate AI

هذا الملف يجمع كل ما بتحتاجه  للتكامل مع خدمة الذكاء الاصطناعي: الـ endpoints الجاهزة، البيانات المُسلَّمة، خطوات التشغيل، والمطلوب منكم.

---

## 1. الخدمة: ما هي وأين تعمل
خدمة مستقلة (Python / FastAPI)  تستقبل نصاً طبيعياً (عربي/إنجليزي) وترجّع JSON منظم. لا تخزّن بيانات دائمة.

تأكد من تشغيل الخدمة على بيئتك المحلية لتستطيع الوصول للتوثيق التفاعلي Swagger عبر:
[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 2. خطوات تشغيل المشرف محلياً (Quick Start)
لتشغيل تطبيق الـ FastAPI
---------------------------------------------------
# 1. إنشاء البيئة الافتراضية
python -m venv venv

# 2. تفعيل البيئة الافتراضية
# على Linux/macOS:
source venv/bin/activate
# على Windows:
venv\Scripts\activate

# 3. تثبيت المكتبات المطلوبة
pip install -r requirements.txt

# 4. إعداد المتغيرات البيئية
cp .env.example .env
# (قم بتحديث المفاتيح داخل ملف .env إن لزم الأمر)

# 5. تشغيل السيرفر
uvicorn main:app --reload --port 8000
-------------------------------------------------------

3. المتغيرات البيئية وشكل ملف 
تأكد من وجود ملف .env في جذر المشروع يحتوي على القيم التالية:
-----------------------------------------------
# Server Configuration
PORT=8000
ENVIRONMENT=development

# AI Model Configuration (Free External AI Model)
AI_MODEL_API_KEY=your_free_ai_model_api_key_here
AI_MODEL_URL=https://api.external-ai-provider.com/v1

# Database SQL Dump Backup Path (Temporary)
LOCAL_DB_PATH=./database_final.sql
----------------------------------------------

4. الـ Endpoints الجاهزة للتكامل

### A ) POST /api/search/ai-contextual — فهم النية
يحوّل نص المستخدم لمعايير بحث منظمة.

**الطلب:**
```json
{ "raw_text": "شقة بأقل من 600 ألف درهم" }
```

**الرد:**
```json
{
  "property_type": "Apartment",
  "max_budget": 600000,
  "budget_currency": "AED",
  "min_bedrooms": null,
  "vibe_tags": ["quiet", "near_cafes"],
  "required_amenities": [],
  "location_hint": null,
  "confidence": 1.0,
  "needs_clarification": false
}
```

**ملاحظات مهمة:**
- `property_type` نص مطابق تماماً لـ `property_type_en` عندكم (Apartment, Villa, Office...)
- `needs_clarification: true` يعني النص غامض — اعرضوا للمستخدم رسالة توضيح بدل البحث
- `vibe_tags` وصفية حرة (للاستخدام المستقبلي) — لا تُطابَق بأي حقل عندكم حالياً

### B ) `POST /api/search/find-properties` — البحث الكامل
نفس المدخل، لكن يرجّع **العقارات المطابقة فعلياً** إضافة لفهم النية.

**الرد:**
```json
{
  "parsed_criteria": { ... },
  "matches_found": 3,
  "properties": [ { ...كامل بيانات العقار... } ]
}
```

### C ) `POST /api/properties/vibe-report` — تقرير المحيط (US-08)
**الطلب:**
```json
{ "property_id": "PROP_10211", "latitude": 25.21227, "longitude": 55.27946 }
```

**الرد:**
```json
{
  "property_id": "PROP_10211",
  "safety_score": 7.5,
  "quietness_score": 3.5,
  "amenities_score": 8.0,
  "reviews_analyzed": 12,
  "data_confidence": "sufficient"
}
```

- الدرجات من 0 إلى 10
- `data_confidence: "pending_more_data"` يعني بيانات غير كافية (أقل من 3 مراجعات بالمحيط) — لا تعرضوا الدرجات كحقيقة بهذه الحالة

### D ) `POST /api/reviews/analyze` — تحليل مراجعة واحدة (US-10)
```json
{ "text": "المكان نظيف بس صاخب بالليل", "source": "user_submitted" }
```

---

## 5. البيانات المُسلَّمة لكم

### `dubai_pois.json` — 6,551 نقطة اهتمام حقيقية بدبي
مصدرها OpenStreetMap (ترخيص ODbL — يتطلب نسب المصدر عند النشر العلني).

**الشكل:**
```json
{
  "osm_id": 315524193,
  "name": "Dubai Old Souk - Abra dock",
  "category": "amenities",
  "latitude": 25.2649926,
  "longitude": 55.2952522
}
```

**الفئات الأربع:** `safety` (مستشفيات/عيادات/مخافر) · `quietness_positive` (حدائق) · `quietness_negative` (بارات/نوادي) · `amenities` (مطاعم/صيدليات/مواصلات)

**جدول مقترح للتخزين:**
```sql
CREATE TABLE points_of_interest (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(50) NOT NULL,
    latitude DECIMAL(10,7) NOT NULL,
    longitude DECIMAL(10,7) NOT NULL
);
CREATE INDEX idx_poi_category ON points_of_interest (category);
```

**استعلام محيط 500 متر (بدون PostGIS):**
```sql
SELECT *, (6371000 * acos(
    cos(radians(:lat)) * cos(radians(latitude)) *
    cos(radians(longitude) - radians(:lng)) +
    sin(radians(:lat)) * sin(radians(latitude))
)) AS distance_m
FROM points_of_interest
HAVING distance_m <= 500
ORDER BY distance_m;
```

---

## 6. المطلوب منكم

###A) endpoint يرجّع كل العقارات أو يدعم الفلترة

`/api/home` يرجّع 12 عقار فقط (عقارات مميزة للصفحة الرئيسية)، بينما قاعدة البيانات فيها 708 عقار. هذا يمنع البحث من العمل فعلياً

**المطلوب أحد الاثنين:**
1. **الأفضل:** `GET /api/properties?type=Apartment&max_price=600000&community=Business Bay`

2. **بديل مقبول:** `GET /api/properties` يرجّع كل العقارات (مع pagination)

**حل مؤقت حالي:** خدمة الذكاء الاصطناعي تقرأ نسخة محلية من `database_final.sql` (706 عقار) بدل الاتصال الحي — هذا غير مستدام، ولن يعكس أي عقارات جديدة تضيفونها.



###B ) سؤال: هل ستُضاف بيانات المرافق (Amenities)؟
المخطط الحالي لا يحتوي على أي جدول مرافق. إن كانت هناك خطة لإضافتها، أخبرونا لنجهّز المطابقة مسبقاً.

---

## 7. قيود يجب معرفتها

| القيد | الأثر عليكم |
|---|---|
| **الخدمة تعتمد على موديل ذكاء اصطناعي مجاني خارجي** | قد تفشل مؤقتاً وقت الذروة وترجّع needs_clarification: true أو درجات محايدة (5.0). عالجوا هذه الحالة بالواجهة — اعرضوا رسالة "حاول مجدداً" بدل نتيجة فارغة |

| **المراجعات مولّدة اصطناعياً** |
موسومة بـ 
"source": "synthetic_deepseek_v1". لا تُعرض كمراجعات مستخدمين حقيقيين|



---

## 8. التعامل مع الأخطاء

الخدمة **لا ترجّع 500 أبداً** —
- فشل الذكاء الاصطناعي → `needs_clarification: true` مع `confidence: 0`
- بيانات محيط غير كافية → `data_confidence: "pending_more_data"` مع درجات 5.0 محايدة

**تعاملوا مع هاتين الحالتين بالواجهة** ولا تعرضوهما كنتيجة نهائية للمستخدم.

---



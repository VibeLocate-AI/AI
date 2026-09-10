# تسليم بيانات نقاط الاهتمام (POIs) — دبي
## من: مهندس الذكاء الاصطناعي | إلى: فريق الباك اند (Laravel)

---

## 1. شو هاي البيانات؟

مجموعة من **الأماكن الحقيقية بمدينة دبي** (مطاعم، مستشفيات، حدائق، بارات، صيدليات، محطات مواصلات...)، مسحوبة من **OpenStreetMap** عبر Overpass API. هذه البيانات تغذّي ميزة **"Neighborhood Vibe Report"** (US-08 بالـ SRS) — حساب درجات الأمان والهدوء والخدمات بمحيط 500 متر حول أي عقار.

**الملف:** `dubai_pois.json`
**الحجم التقريبي:** ~6,551 عنصر (قد يختلف قليلاً حسب وقت آخر سحب)
**المصدر:** OpenStreetMap (بيانات مفتوحة، مرخّصة تحت ODbL)

---

## 2. شكل البيانات (Schema)

الملف عبارة عن **مصفوفة JSON**، كل عنصر فيها بهذا الشكل:

```json
{
  "osm_id": 315524193,
  "name": "Dubai Old Souk - Abra dock",
  "category": "amenities",
  "latitude": 25.2649926,
  "longitude": 55.2952522
}
```

| الحقل | النوع | الوصف |
|---|---|---|
| `osm_id` | integer | معرّف فريد من OpenStreetMap — **يُستخدم كمفتاح فريد (unique key) لتجنب التكرار عند الاستيراد** |
| `name` | string | اسم المكان. قد يكون `"Unnamed"` لأماكن بدون اسم مسجّل بـ OSM — **يُنصح استبعادها عند الاستيراد الفعلي** |
| `category` | string | واحدة من 4 قيم ثابتة (انظر القسم التالي) |
| `latitude` | float | خط العرض (WGS84) |
| `longitude` | float | خط الطول (WGS84) |

---

## 3. الفئات الأربع (`category`) — وربطها بـ Vibe Report

كل فئة تغذّي بُعداً مختلفاً من أبعاد الـ **VibeReport** الثلاثة الموصوفة بالـ Class Diagram (SRS، فصل 4):

| قيمة `category` | تشمل | تُستخدم لحساب |
|---|---|---|
| `safety` | مستشفيات، عيادات، مخافر | `safety_score` |
| `quietness_positive` | حدائق، مناطق ترفيهية | `quietness_score` (تأثير إيجابي) |
| `quietness_negative` | بارات، نوادي ليلية | `quietness_score` (تأثير سلبي) |
| `amenities` | مطاعم، مقاهي، صيدليات، سوبرماركت، محطات مواصلات | `amenities_score` |

**ملاحظة:** التوزيع الفعلي غير متساوٍ — الغالبية العظمى (~92%) تقع تحت `amenities` لأنها الأكثر شيوعاً بأي مدينة. هذا طبيعي وليس خطأ بالبيانات.

---

## 4. الاستخدام المقترح بالباك اند

### أ. التخزين
يُفضّل استيراد هذه البيانات إلى جدول منفصل بقاعدة PostgreSQL/PostGIS (كما هو موصوف بمعمارية النظام، SRS فصل 4.1.1)، مثال لبنية جدول مقترحة:

```sql
CREATE TABLE points_of_interest (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(50) NOT NULL,
    location GEOGRAPHY(POINT, 4326) NOT NULL,  -- PostGIS
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_poi_location ON points_of_interest USING GIST (location);
CREATE INDEX idx_poi_category ON points_of_interest (category);
```

### ب. الاستعلام (مثال لحساب دائرة 500 متر)
```sql
SELECT name, category,
       ST_Distance(location, ST_MakePoint(:property_lng, :property_lat)::geography) AS distance_m
FROM points_of_interest
WHERE ST_DWithin(location, ST_MakePoint(:property_lng, :property_lat)::geography, 500)
ORDER BY distance_m;
```

### ج. التكامل مع خدمة الذكاء الاصطناعي
بعد ما الباك اند يجيب قائمة الأماكن ضمن 500 متر، يُرسل نصوص المراجعات المرتبطة فيها (إن وُجدت) إلى:

```
POST /api/reviews/vibe-report
```

(موثّق بالكامل بوثيقة الـ API المنفصلة — راجع endpoint `/docs` بخدمة الذكاء الاصطناعي)

---

## 5. قيود مهمة يجب معرفتها

- **البيانات لحظة سحب واحدة (snapshot)** — لا تتحدّث تلقائياً. أي منشأة جديدة فتحت بدبي بعد تاريخ السحب لن تظهر، إلا بإعادة تشغيل سكريبت الجلب (`fetch_dubai_pois.py`) يدوياً
- **الترخيص**: بيانات OpenStreetMap مرخّصة تحت **ODbL** — استخدام مفتوح، لكن يتطلب نسب المصدر عند النشر العلني (attribution) حسب شروط الترخيص
- **لا يوجد نص مراجعات مرفق بهذا الملف** — هذا الملف بيانات موقعية (POI) بس. نصوص المراجعات (حقيقية أو مصطنعة للـ MVP) تُدار بملف/عملية منفصلة تماماً، وستُسلَّم لاحقاً

---

## 6. عند دمج بيانات جديدة (مثل بيانات عقارات/مباني)

إذا وصلت بيانات إضافية بنفس الصيغة تقريباً (اسم، فئة، إحداثيات) من مصدر آخر، يمكن دمجها بنفس الجدول أعلاه طالما:
1. تحويل أسماء الحقول لتطابق نفس الـ Schema أعلاه (`name`, `category`, `latitude`, `longitude`)
2. التأكد من عدم تكرار `osm_id` — للبيانات من مصدر غير OSM، يُستخدم معرّف بديل فريد بدلاً منه

---

**للتواصل بخصوص هذا الملف أو أي استفسار تقني:** [مهندس الذكاء الاصطناعي]
**تاريخ آخر سحب للبيانات:** يُحدَّد تلقائياً عند تشغيل `fetch_dubai_pois.py` (راجع حقل `generated_at` بملف `manifest.json` المرفق)
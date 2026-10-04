import json

# 1. قراءة ملف الـ JSON
with open('handoff/dubai_pois.json', 'r', encoding='utf-8') as f:
    pois = json.load(f)

# 2. إنشاء ملف SQL
with open('handoff/dubai_pois.sql', 'w', encoding='utf-8') as f:    # كتابة هكيل الجدول أولاً (اختياري لتسهيل الأمر عليه)
    f.write("""-- إنشاء جدول نقاط الاهتمام في PostgreSQL/PostGIS
CREATE TABLE IF NOT EXISTS points_of_interest (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(50) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    location GEOGRAPHY(POINT, 4326),
    created_at TIMESTAMP DEFAULT NOW()
);

-- إدراج البيانات
""")

    # كتابة أوامر الإدخال
    for item in pois:
        osm_id = item.get('osm_id')
        name = item.get('name', 'Unnamed').replace("'", "''")  # معالجة العلامات المزدوجة في الأسماء
        category = item.get('category')
        lat = item.get('latitude')
        lng = item.get('longitude')
        
        # استبعاد الأماكن التي ليس لها اسم إن رغبت
        if not osm_id or not lat or not lng:
            continue

        sql_line = f"""INSERT INTO points_of_interest (osm_id, name, category, latitude, longitude, location) 
VALUES ({osm_id}, '{name}', '{category}', {lat}, {lng}, ST_SetSRID(ST_MakePoint({lng}, {lat}), 4326)::geography)
ON CONFLICT (osm_id) DO NOTHING;\n"""
        
        f.write(sql_line)

print("تم تحويل البيانات بنجاح إلى ملف dubai_pois.sql!")
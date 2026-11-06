# Yol haritası (07.11.2026)

Amaç: senin "işlem alırdım" dediğin kurulumları doğru günde veren, sanal portföyde kendini kanıtlamış bir sistem.
Kural: her değişiklik ÖNCEDEN YAZILMIŞ ölçütle test edilir; geçmeyen kural eklenmez. Hız, işaretlerin birikmesine bağlı.

Durum: ⬜ başlamadı · 🔄 sürüyor · ✅ bitti · ❌ red

## 0. Altyapı (bitti)
- ✅ Telegram butonları (alırdım / başka gün / almazdım, stage, çizgi yanlış), `direnç X` ve `kaçan` mesajları
- ✅ Python = Pine eşitliği (05.11 EMA kapısı hatası düzeltildi)
- ✅ Base v0 kör test (%62) → taramada gölge; yeni arzlar 30 günden itibaren
- ✅ Sanal portföy (100.000 TL, %1 risk, 5 işlem, Iz10 kapanışla) → 09.11.2026 akşamı başlıyor
- ✅ Geriye dönük portföy testi (açılıştan alım, kayma, hacim filtresi, rastgele seçim)
- ❌ Base v1 / v2 / v3 / v0b (ön kontrol ya da yoğunluk ölçütü geçmedi)
- ❌ Giriş yenileme, zamanlama örnekleminde fark yaratmadı → gölge portföyde ileri teste aday

## 1. Çizgi seçimi · tahmini 1–2 hafta · ⬜
- Veri: 20–30 `direnç X` cevabı (ana gösterge + Base grafiklerinde)
- Aday yöntemler: seviyeyi gövdeden bulmak (levelSrc=Gövde), yatayı düşen çizgiye tercih (hPrefer / flatPrefer),
  en çok değilen seviye
- Kabul: senin çizgine ortalama uzaklık en küçük olan + kalibrasyonda doğru etiket sayısı düşmez → Pine'a eklenir

## 2. Giriş kalitesi · tahmini 2–3 hafta (1 ile paralel) · ⬜
- Kırılım mumu kalitesi (TCKRC): Giriş mumu son mumlardan belirgin büyük ve direncin üstünde kapanır
- Çizgi altında daralma (INDES, MOBTL): Giriş'ten önceki 2–3 mum direncin hemen altında
- Giriş yenileme: gölge portföyde ileri test
- Ölçüm: zamanlama örneklemi + geriye dönük test (rastgele seçimli) + ileri test işaretleri

## 3. Kurulum filtresi · 30–50 işaretten sonra (3–5 hafta) · ⬜
- E50 (ana kural), stage işaretleri, V dönüşü / kümelenme süresi (OZYSR)
- "Almazdım" dediklerini etiket aşamasında elemek

## 4. Base modu · 20–30 kaçandan sonra · ⬜
- s1 / s2 base'ler ayrı analiz; v0'ın takıldığı şartlar (20 mum penceresi, temas)
- Base için daha yakın stop (base dibi bazen -%20)

## 5. Sinyal seçimi ve portföy · 3 ve 4'ten sonra · 🔄
- Yer yokken hangi sinyal alınır (sıralama kuralı) — geriye dönük testte en büyük şans faktörü
- İşlem sayısı / risk oranı (5, 10, 15 işlem varyantları test ediliyor)

## 6. Doğrulama · 2–3 ay · ⬜
- Sanal portföy sabit kurallarla; başarı ölçütü önceden yazılır (örn. en az 50 işlem, PF > 1.5, en büyük düşüş sınırı)
- Geçerse yarı otomatik (bot emir önerir, onay senden)

## Senin tarafın (her gün / hafta)
- Gelen grafiklere buton; çizgi yanlışsa 📐 + `direnç X`; almadıklarına kısa not
- Kaçırdıkların: `kaçan KOD GG.AA base s1` / `base s2`
- Haftada bir "Ileri test ozeti"

## Tahmini süre
1–4. adımlar ~1–1,5 ay, doğrulama ~2–3 ay → güvenilir sisteme ~3–4 ay (veri akışına ve test sonuçlarına bağlı).

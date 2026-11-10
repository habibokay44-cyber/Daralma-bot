# Yol haritası (güncelleme 09.11.2026)

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

## 1. Çizgi seçimi · ⏸ canlı veri bekliyor
- Ölçüm: göstergenin seviyesi senin seviyene zaten yakın (medyan 0.64 ADR); fark çizginin ŞEKLİ ve hangi tepenin seçildiği
- ❌ 07.11 çizgi ayarları sıkılaştırma / yeni çizgi (cizgi_test) — ölçüt geçmedi
- ❌ 07.11 Giriş yatay kırılım şartı GY1 / GY2 — kötü 2–3/7 kalktı (ölçüt 5)
- ❌ 07.11 en çok temas eden çizgi TM1 / TM2 — kötüleri temizledi ama iyilerin 4–6/14'ü kaldı (ölçüt 12)
- Sonuç: seçimin bağlama bağlı (IHYAY'da uzun eski çizgi, ENKAI'de yeni alçak base tepesi); basit kural yakalamıyor.
  Aynı 7 kötü örnekle denemeye devam = kural uydurma. Canlı `direnç X` cevapları birikince yeni testle dönülecek.
- Yan bulgu (karar değil): V3 fitil payı ve GY1 kalibrasyonda yanlış etiketi 14 → 11'e indiriyor; ayrı test adayı

## 2. Giriş kalitesi · tahmini 2–3 hafta (1 ile paralel) · ⬜
- Kırılım mumu kalitesi (TCKRC): Giriş mumu son mumlardan belirgin büyük ve direncin üstünde kapanır
- Çizgi altında daralma (INDES, MOBTL): Giriş'ten önceki 2–3 mum direncin hemen altında
- Giriş yenileme: gölge portföyde ileri test
- Ölçüm: zamanlama örneklemi + geriye dönük test (rastgele seçimli) + ileri test işaretleri

## 3. Kurulum filtresi · 30–50 işaretten sonra (3–5 hafta) · ⬜
- E50 (ana kural), stage işaretleri, V dönüşü / kümelenme süresi (OZYSR)
- "Almazdım" dediklerini etiket aşamasında elemek

## 4. Base modu · 🔄 v0 kabul, filtre için canlı veri
- ✅ Base v0 iki kör testte tutarlı: %62 (39 grafik), %58 (T2 örneklemi, 40 grafik)
- ❌ 08.11 Base T2 (en az 2 ayrı temas, kırılım mumu sayılmaz), YENİ 40 kör grafikte: geçen alırdım %65, elenen %50
  (ölçüt: >= %70 ve 20 puan fark)
- 08.11 ayırt ölçümü (73 grafik, 12 ölçü): hiçbir ölçü tek başına ayırmıyor (en iyi AUC 0.65–0.68: temas sayısı,
  tepelerin dağınıklığı, base yüksekliği)
- ÖNEMLİ BULGU: senin `direnç` cevabın ayırıyor — "direnç yok" dediğin 16 grafiğin 14'ü almazdım, fiyat yazdığın 12'nin
  12'si alırdım/başka gün. Yani karar geometriden çok senin bütüne bakışın → canlı Base sinyallerinde `direnç` cevabı
  yazmaya devam; birkaç yüz işaretle ileride öğrenen model adayı
- Bekleyen: kaçan base listesi (ESEN, SVGYO, KTLEV, RALYH, ...) 20–30'a çıkınca s1/s2 ve kaçış nedenleri;
  Base için daha yakın stop (base dibi bazen -%20)

## 5. Sinyal seçimi ve portföy · 3 ve 4'ten sonra · 🔄
- Yer yokken hangi sinyal alınır (sıralama kuralı) — geriye dönük testte en büyük şans faktörü
- ✅ İşlem sayısı / risk: geriye dönük testte 15 işlem %0.5 risk en dar aralığı verdi (en kötü 3,5 / medyan 4,7 milyon),
  5 işlem %1 risk en geniş (1,7 / 4,6 / 13,6 milyon). KARAR (07.11.2026, kullanıcı): **5 işlem, %1 risk** — gerçekçi ve
  kullanıcının işlem tarzı. Sonuç: 5 yerde şans faktörü büyük → sinyal kalitesi (1–4) ve sıralama kuralı daha da önemli.

## 6. Doğrulama · 2–3 ay · ⬜
- Sanal portföy sabit kurallarla; başarı ölçütü önceden yazılır (örn. en az 50 işlem, PF > 1.5, en büyük düşüş sınırı)
- Geçerse yarı otomatik (bot emir önerir, onay senden)

## 09.11.2026 sonuçları (yöntem değişikliği: kararlar getiriyle ve büyük örnekle)
- ✅ İşaret-getiri testi (235 kör işaret): DARALMADA 'alırdım' +1.1…+1.6R (PF 3-4.7), 'almazdım' -0.2…-0.3R (PF 0.65-0.70),
  fark %90 aralıkla sıfırın üstünde. BASE'de fark yok (PF 1.83'e 1.84) -> Base'de 'direnç var mı' kurallarına emek harcanmayacak.
- ✅ Onaylı gölge portföy (state/portfoy_onay.json): aynı kurallar, sadece ✅ denen sinyaller; canlıda aynı fark var mı.
- ❌ Daralma modeli v1 (161 işaret, 26 ölçü, lojistik): AUC 0.65 (eşik 0.68), puan getiriyi sıralamıyor. İşaret biriktikçe tekrar.
- ❌ RS60 / RS120 sıralaması: iki dönemde de rastgele seçimin medyanının altında. Sıralama kuralı değişmedi.
- ✅ V3 (wickADR 2.5 -> 0.5) iki dönemli varyant testi (2.683 Giriş): iki dönemde de ort. R yüksek; attığı 366 sinyal ort +0.07R
  -> Python'da ve Pine'da devrede (09.11.2026 akşamından sonra).
- ❌ GY1: attığı 610 sinyal ort +1.48R (kalanlardan iyi) -> red. Not: 'düşen çizgi kırılımı' Giriş'leri ortalamada kârlı.
- ✅ Veri: tarama temettü düzeltilmiş TradingView verisi (Pine ADJ ile aynı); Pine'da eksik Y / H şartları eklendi.
- ⚠️ 10.11.2026 ÖLÇÜ DÜZELTMESİ: tek tek işlem testlerinde R, çok yakın stoplu işlemlerde şişiyordu (portföyde işlem en fazla
  özsermayenin 1/5'i). Yeni ölçü: portföy-eşdeğeri R. Sistem ort. D1 +0.54R, D2 +0.80R (eski ölçüyle +0.96 / +1.08 görünüyordu).
  V3 yeni ölçüyle kıl payı RED (aralık -0.03 … +0.77) -> wickADR 2.5'e GERİ ALINDI (Python + Pine). GY1 yine red.
  Çıkış / piyasa filtresi / sadeleştirme testleri yeni ölçüyle yeniden çalıştırılıyor; 10.11 sabahki 'işe yarıyor' listesi geçersiz.
- ❌ Örneklem 5 (model alt çeyreği, 39 kör işaret): iyi kurulum %55'e %58 -> red. Bu örneklemde alırdım -0.03R, almazdım +0.07R
  (n=39, tek başına 09.11 bulgusunu çürütmez; onaylı gölge portföy belirleyecek).
- ✅ Canlı dinleme (dinle.yml): buton basışları Telegram'da beklerken kayboluyordu; işaretlemeden önce dinleme açılır.
- 10.11 çıkış / piyasa (düzeltilmiş ölçü): piyasa filtreleri, EMA21 çıkışı, +2R stopu red. Iz20 tek tek işlemde 3 ölçütü geçti
  ama portföy benzetiminde doğrulanmadı (4 karşılaştırmanın 2'si) -> Iz10 kalır. Kural: canlıya almadan önce İKİ ölçü.
- 10.11 sadeleştirme (24 filtre tek tek kapatıldı): iki ölçüde de aynı çıkan tek filtre 'dipler kontrolü' (zararlı yönde).
  ✅ useLows KAPATILDI (kullanıcı onayı, 10.11): engellediği 217 Giriş %36 kazanma / +2.71R (kalan %29 / +0.66R), iki dönemde de
  ort. yükseliyor, kalibrasyon 51/14 aynı, PF 1.82 -> 1.89. Diğerleri: 6'sı ana ölçüde işe yarıyor (kırmızı mum, EMA21 kapısı,
  art arda düşüş, H, iptal kırmızı mum, iptal düşüş), 14'ü getiri açısından etkisiz (göz uyumu için kalıyor), 3'ü ölçülemez.
- Bekleyen: Pine = Python otomatik karşılaştırma (TradingView CSV dışa aktarımı gerekir).

## Takvim
- 09.11.2026 akşamı: sanal portföy başlar (ilk 💼 mesajı)
- 12.11.2026 19:31: tutarlılık kontrolü (10 eski grafik, eski işaretler gizli)

## Senin tarafın (her gün / hafta)
- Gelen grafiklere buton; çizgi yanlışsa 📐 + `direnç X`; Base sinyallerinde `direnç X` ya da `direnç yok`; almadıklarına kısa not
- Kaçırdıkların: `kaçan KOD GG.AA base s1` / `base s2`
- Haftada bir "Ileri test ozeti"

## Tahmini süre
1–4. adımlar ~1–1,5 ay, doğrulama ~2–3 ay → güvenilir sisteme ~3–4 ay (veri akışına ve test sonuçlarına bağlı).

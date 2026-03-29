# ZENITH SPACEPORT OS: 
## Kapsamlı Hava Durumu Destekli 2-Serbestlik Dereceli Roket Simülasyonu ve Otonom GNC (Güdüm, Navigasyon, Kontrol) Mimarisi Üzerine Teknik Analiz

***

## İÇİNDEKİLER
1. [Özet](#1-öze-abstract)
2. [Giriş ve Arka Plan](#2-g-r-ş-ve-arka-plan)
3. [Matematiksel Fizik Modelleri](#3-matemat-ksel-f-z-k-modeller)
   3.1. Uluslararası Standart Atmosfer (ISA) ve Termodinamik
   3.2. Aerodinamik Sürtünme ve Rüzgar Vektörleri
   3.3. Tsiolkovsky Roket Denklemi ve Dinamik Özgül İtki (Isp)
4. [GNC ve Yörünge Hareketliliği](#4-gnc-ve-yörünge-hareketl-l-ğ)
   4.1. Gravity Turn (Yerçekimi Dönüş Kapsamı)
   4.2. Vis-Viva Denklemi ve SECO Otonomisi
5. [Telemetri, Veri Analizi ve Veritabanı Mimarisi](#5-telemetr-ver-anal-z-ve-ver-tabani-m-mar-s)
6. [Sonuç ve Gelecek Geliştirmeler](#6-sonuç-ve-gelecek-gel-şt-rmeler)
7. [Referans Denklemler ve Sabitler](#7-referans-denklemler-ve-sab-tler)

***

## 1. Özet (Abstract)
Günümüzde uzay fırlatma sistemlerinin operasyonel başarısı, yalnızca güçlü motorların tasarımına değil; fırlatma anındaki atmosferik koşulların doğru hesaplanmasına, uçuş sırasındaki anlık aerodinamik basıncın (Max-Q) analizine ve yörünge yerleşimi sırasındaki otonom motor kapatma (SECO) algoritmalarının hassasiyetine bağlıdır. Bu detaylı teknik raporda, Python dili ve **Zenith Spaceport OS** mimarisi üzerinde inşa edilmiş, 2 serbestlik derecesine (2-DOF) sahip, otonom kararlar alabilen bir roket uçuş simülasyon motoru analiz edilmektedir. Sistem, dış havadan aldığı statik değerler yerine OpenWeatherMap arayüzünden anlık "reverse-geocoding" ile lokal meteorolojik sensör verisini çeker, yoğunluk hesaplarını bu dinamik veri setine göre yapar ve fırlatma aracının (örn. Falcon 9, Starship) aerodinamik ve termodinamik dengesini haritalandırır.

## 2. Giriş ve Arka Plan
Uzay uçuş simülatörleri endüstriyel olarak oldukça fazla kaynak tüketen 6-Serbestlik Derecesine (6-DOF) sahip platformlar olarak geliştirilir. Ancak hesaplamalı astrofizik baz alındığında, iki boyutlu bir kartezyen sistem (X-Y aksları) üzerinde 2-DOF bir çözümleme, enerji sarfiyatını, ivmeyi, vis-viva etkilerini ve Max-Q katsayılarını analiz etmek için akademik çerçevede tamamen yeterlidir.

Geleneksel roket denklemi, sabit bir $\Delta V$ gereksinimi sunar. Gerçek hayatta ise rüzgâr direnci ($F_{wx}$), irtifa kaynaklı basınç kaybı ve buna bağlı motor verimi (Isp) sürekli değişim içindedir. **Zenith Spaceport OS**, veri madenciliği araçları (Pandas), bilimsel gösterim kütüphaneleri (Plotly) ve Streamlit reaktif çerçevesini kullanarak statik bir script çözümünü interaktif bir panele çevirmeyi başaran, hava ve roket verilerinin eşzamanlı aktığı tam tur (end-to-end) bir yazılım projesidir.

***

## 3. Matematiksel Fizik Modelleri

### 3.1. Uluslararası Standart Atmosfer (ISA) ve Termodinamik
Zenith sistemindeki motor, her $0.05$ saniyelik karede (Euler İtegrasyonu kullanarak) etrajındaki hava kütlesini ölçer. Troposfer ($<11.000$ m) ve Stratosfer ($11.000m - 20.000m$ vb.) katmanlarındaki ısı dengesizliği simülasyona aktarılmıştır.

Lokal Sıcaklık Denklemi:
Lapse rate (sıcaklık düşüş katsayısı) $0.0065$ K/m olarak alınır:
$T_{local} = T_{sea} - (0.0065 \cdot y)$ ->  *(Alt 11km için)*

Barometrik Basınç Denklemi:
Rakıma ve sıcaklığa bağlı basınç çöküşü üstel (eksponansiyel) bir formül ile modellenmiştir:
$$ P_{local} = P_{sea} \cdot e^{ \left( \frac{-M \cdot g_0 \cdot y}{R_{universal} \cdot T_{sea}} \right) } $$
Burada $M = 0.02896$ kg/mol (havanın molar kütlesi) ve $R_{universal} = 8.314$ J/(mol·K)'dur. Bu denklem atmosferin üst kısımlarına doğru roket üzerindeki baskının ve sürtünmenin nasıl logaritmik olarak kaybolduğunu kanıtlar.

Genişletilmiş İdeal Gaz Yasasıyla Atmosferik Özkütle:
$$ \rho = \frac{P_{local}}{R_{specific} \cdot T_{local}} $$

### 3.2. Aerodinamik Sürtünme ve Rüzgar Vektörleri
Rokete binen aerodinamik stresi ölçmek için, sistem önce havanın süratini (V_air) kendi X ve Y hızlarından türetir. Mak (Mach) sayısı $V_{air} / a_{sound}$ ile hesaplanır; burada $a_{sound} = \sqrt{1.4 \cdot R_{specific} \cdot T_{local}}$ ile bulunur.
Roket ses hızını aşarken ($0.8 \le Mach \le 1.2$ dönemi - transonik bölge) sürtünme katsayısı ($C_d$) %250 oranında modifiye edilerek fiziksel şok dalgaları simüle edilir. 

Dinamik Basınç (Q):
$$ q = \frac{1}{2} \rho \cdot V_{air}^2 $$
Simülasyon bu basıncın tepe noktaya (Max-Q) ulaştığı saniyeyi yakalar. Max-Q noktası, roket gövdesine binen aerodinamik stresin tepe yaptığı, dolayısıyla ivmenin veya itkinin kısılması gerektiği bölümdür. Rüzgar verisi OpenWeatherAPI'den yatay bir yönelim (wind_deg) ile $F_{wx}$ yanal sürtünmesini ekleyerek roketi bir ray üzerinde düz gitmekten saptırır, motor bu rüzgarı tolere etmek zorundadır.

### 3.3. Tsiolkovsky Roket Denklemi ve Dinamik Özgül İtki (Isp)
Simülasyon roketin atmosfer dışına çıktığını ve motorun yanma odasındaki egzozun nozülden daha kolay dışarı atıldığını otonom anlar. Vakum (uzay) Isp değeri ve Deniz Seviyesi Isp değeri arasında lineer bir entegrasyon çözülür:
$$ Isp_{dinamik} = Isp_{sea} + (Isp_{vac} - Isp_{sea}) \cdot \left(1 - \min(1.0, P_{local} / P_{sea})\right) $$
Kalan Manevra Kapasitesinin ($\Delta V$) anlık takibi Tsiolkovsky denkleminin entegrasyonudur:
$$ \Delta V = Isp_{dinamik} \cdot g_0 \cdot \ln\left(\frac{m_0}{m_1}\right) $$
Her $dt$ anında, kalan yakıt ve fırlatılan kütle arasındaki bu logaritmik oran, sistemin ne kadar yakıtı kaldığını UI üzerinde gösterir. Kademeler (Stages) ayrıldığında, kuru kütle (dry mass) atıldığı için $\Delta V$ tekrar ivmelenir.

***

## 4. GNC ve Yörünge Hareketliliği

Güdüm (Guidance), roketin yörünge eğrisini uzay boşluğunda kendi başına seçebilmesidir.

### 4.1. Gravity Turn (Yerçekimi Dönüş Kapsamı)
Sistem $2000$ metre irtifadan başlayarak yörünge ivmesine geçiş yapar. Roket $90^\circ$ dikey açıdan ($Pitch$) çıkıp yavaşça yatay parabol oluşturur. Merkezkaç ivmesi ve yerel kütleçekim kuvvetinden faydalanan iteratif kod:
$$ g_{local} = \frac{\mu}{r^2} \quad | \quad a_{centrifugal} = \frac{V_x^2}{r} $$
$ a_{required} = \max(0, g_{local} - a_{centrifugal}) $
İstenen hedefle, motorun kapasitesi oranı, $\sin(\theta)$ fonksiyonu içinde kullanılarak optimal "Gravity Turn" açısı üretilir. Böylece yakıt, yerçekimi direncine karşı harcanmak yerine doğrudan yanal hıza ($Orbital Velocity$) döndürülür.

### 4.2. Vis-Viva Denklemi ve SECO Otonomisi
GNC diziliminin parlayan yıldızı Vis-Viva kontrolüdür. Kullanıcı sisteme (örneğin LEO, MEO veya GTO) hedefler verir. Kod bu hedefe "ne kadar hızla ulaşılması gerektiğini" şu enerji sabitiyle çözer:
$$ V_{req} = \sqrt{ \mu  \left( \frac{2}{r} - \frac{1}{R_{earth} + Target\_Perigee} \right) } $$
Roket istenen bu hız eşiğini teğet geçtiği mikrosaniyede, itki denklemi ($current\_thrust$) acımasızca **sıfıra** ($0.0$) eşitlenir. Buna "Second Engine Cut-Off" (SECO) denir. SECO başarıldığında roket ivmesiz (ballistic) yörünge uçuşuna otonom sistem sayesinde hatasız geçmiş olur. Eksantriklik (Eccentricity) ölçülerek yörüngenin dairesel veya parabolik olduğuna karar verilir.

***

## 5. Telemetri, Veri Analizi ve Veritabanı Mimarisi
Zenith Spaceport, simüle ettiği her veriyi 20 Hz, ardından görselleştirme arayüzü olan Streamlit (Plotly Dashboards) üzerinde tarayıcı limiti aşılmasın diye 1 Hz'e rektifiye (downsample) ederek analiz eder:
- **Kütle Optimizasyon Matrisi:** Çoklu kademelerde ağırlık atımında eğrinin "sawtooth" (testere dişi) zıplamalarını yakalayarak izler.
- **Kinetik Paraboller:** Termodinamikte enerjinin yok olmadığı kuralına dayanarak roketin kütleçekimsel Potansiyel Enerjisinin (PE), yörüngesel Kinetik Enerjiye (KE) dönüştüğünü alan grafikleri ile ispatlar.
- **Hava Durumu Beslemesi:** REST API protokolleri kullanılarak alınan statik sıcaklık, basınç okumaları, bir meteoroloji JSON obasında işlenip roketin lokal hava sensörüne basılır.

Uçuş bitiminde 1.5 Milyon hücreye varabilen saf, rektifiye edilmemiş gerçek ham telemetri verisi `flight_telemetry.csv` isimli relasyonel veri dosyasına enjekte edilir.

***

## 6. Sonuç ve Gelecek Geliştirmeler
Bu projenin nihai başarısı, yalnızca bir algoritmanın varlığı değil, tüm bu iteratif ve aşırı derece kompleks aerodinamik ile termodinamik denklemlerin, sıradan bir web arayüzünde saniyeler içerisinde $6000$ adımlık analizler yaparak kusursuz yörünge sonuçları vermesidir. Zenith Spaceport OS, havacılık ve uzay sanayisi yarışmaları (Hackathonlar) için, statik modelleme döneminin bittiğini, makine-meteoroloji otonom entegrasyon çağının başladığını kanıtlar.

*Makale Sonu.*

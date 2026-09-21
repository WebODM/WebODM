# -*- coding: utf-8 -*-
"""Plugin strings, one block per language.

gettext is not used here: it would mean compiling .mo files inside the plugin
folder and reinstalling every time a language is added. These are thirteen short
strings; a dictionary is easier to maintain and easier to contribute to.

To add a language, copy a block and translate it. The key is the code Django
returns from get_language() (lowercase, hyphenated). Anything missing falls back
to English.
"""

BASE = "en"

STRINGS = {
    "en": {
        "dataset": "Preparing images", "split": "Splitting", "merge": "Merging",
        "opensfm": "Camera positions", "openmvs": "Dense point cloud",
        "odm_filterpoints": "Filtering points", "odm_meshing": "Mesh",
        "mvs_texturing": "Texturing", "odm_georeferencing": "Georeferencing",
        "odm_dem": "Elevation model", "odm_orthophoto": "Orthophoto",
        "odm_report": "Report", "odm_postprocess": "Finishing",
        "features": "Features", "matching": "Matching",
        "reconstruction": "Reconstruction", "undistort": "Undistorting",
        "remaining": "remaining", "eta": "done at", "of": "of",
    },
    "pt": {
        "dataset": "Preparar imagens", "split": "Dividir", "merge": "Juntar",
        "opensfm": "Posições das câmaras", "openmvs": "Nuvem densa",
        "odm_filterpoints": "Filtrar pontos", "odm_meshing": "Malha",
        "mvs_texturing": "Textura", "odm_georeferencing": "Georreferenciação",
        "odm_dem": "Modelo de elevação", "odm_orthophoto": "Ortofoto",
        "odm_report": "Relatório", "odm_postprocess": "A terminar",
        "features": "Características", "matching": "Emparelhar",
        "reconstruction": "Reconstrução", "undistort": "Corrigir distorção",
        "remaining": "faltam", "eta": "acaba às", "of": "de",
    },
    "pt-br": {
        "dataset": "Preparando imagens", "split": "Dividir", "merge": "Juntar",
        "opensfm": "Posições das câmeras", "openmvs": "Nuvem densa",
        "odm_filterpoints": "Filtrar pontos", "odm_meshing": "Malha",
        "mvs_texturing": "Texturização", "odm_georeferencing": "Georreferenciamento",
        "odm_dem": "Modelo de elevação", "odm_orthophoto": "Ortofoto",
        "odm_report": "Relatório", "odm_postprocess": "Finalizando",
        "features": "Características", "matching": "Pareamento",
        "reconstruction": "Reconstrução", "undistort": "Corrigindo distorção",
        "remaining": "faltam", "eta": "termina às", "of": "de",
    },
    "es": {
        "dataset": "Preparando imágenes", "split": "Dividir", "merge": "Unir",
        "opensfm": "Posiciones de cámara", "openmvs": "Nube densa",
        "odm_filterpoints": "Filtrar puntos", "odm_meshing": "Malla",
        "mvs_texturing": "Texturizado", "odm_georeferencing": "Georreferenciación",
        "odm_dem": "Modelo de elevación", "odm_orthophoto": "Ortofoto",
        "odm_report": "Informe", "odm_postprocess": "Finalizando",
        "features": "Características", "matching": "Emparejamiento",
        "reconstruction": "Reconstrucción", "undistort": "Corrigiendo distorsión",
        "remaining": "faltan", "eta": "termina a las", "of": "de",
    },
    "fr": {
        "dataset": "Préparation des images", "split": "Découpage", "merge": "Fusion",
        "opensfm": "Positions des caméras", "openmvs": "Nuage dense",
        "odm_filterpoints": "Filtrage des points", "odm_meshing": "Maillage",
        "mvs_texturing": "Texturage", "odm_georeferencing": "Géoréférencement",
        "odm_dem": "Modèle d'élévation", "odm_orthophoto": "Orthophoto",
        "odm_report": "Rapport", "odm_postprocess": "Finalisation",
        "features": "Points caractéristiques", "matching": "Appariement",
        "reconstruction": "Reconstruction", "undistort": "Correction de distorsion",
        "remaining": "restant", "eta": "fini à", "of": "sur",
    },
    "de": {
        "dataset": "Bilder vorbereiten", "split": "Aufteilen", "merge": "Zusammenführen",
        "opensfm": "Kamerapositionen", "openmvs": "Dichte Punktwolke",
        "odm_filterpoints": "Punkte filtern", "odm_meshing": "Netz",
        "mvs_texturing": "Texturierung", "odm_georeferencing": "Georeferenzierung",
        "odm_dem": "Höhenmodell", "odm_orthophoto": "Orthofoto",
        "odm_report": "Bericht", "odm_postprocess": "Abschluss",
        "features": "Merkmale", "matching": "Zuordnung",
        "reconstruction": "Rekonstruktion", "undistort": "Entzerrung",
        "remaining": "verbleibend", "eta": "fertig um", "of": "von",
    },
    "it": {
        "dataset": "Preparazione immagini", "split": "Divisione", "merge": "Unione",
        "opensfm": "Posizioni delle camere", "openmvs": "Nuvola densa",
        "odm_filterpoints": "Filtraggio punti", "odm_meshing": "Mesh",
        "mvs_texturing": "Texturizzazione", "odm_georeferencing": "Georeferenziazione",
        "odm_dem": "Modello di elevazione", "odm_orthophoto": "Ortofoto",
        "odm_report": "Rapporto", "odm_postprocess": "Completamento",
        "features": "Caratteristiche", "matching": "Abbinamento",
        "reconstruction": "Ricostruzione", "undistort": "Correzione distorsione",
        "remaining": "mancano", "eta": "finisce alle", "of": "di",
    },
    "nl": {
        "dataset": "Beelden voorbereiden", "split": "Splitsen", "merge": "Samenvoegen",
        "opensfm": "Cameraposities", "openmvs": "Dichte puntenwolk",
        "odm_filterpoints": "Punten filteren", "odm_meshing": "Mesh",
        "mvs_texturing": "Textuur", "odm_georeferencing": "Georeferentie",
        "odm_dem": "Hoogtemodel", "odm_orthophoto": "Orthofoto",
        "odm_report": "Rapport", "odm_postprocess": "Afronden",
        "features": "Kenmerken", "matching": "Matchen",
        "reconstruction": "Reconstructie", "undistort": "Vervorming corrigeren",
        "remaining": "resterend", "eta": "klaar om", "of": "van",
    },
    "pl": {
        "dataset": "Przygotowanie zdjęć", "split": "Podział", "merge": "Scalanie",
        "opensfm": "Pozycje kamer", "openmvs": "Gęsta chmura punktów",
        "odm_filterpoints": "Filtrowanie punktów", "odm_meshing": "Siatka",
        "mvs_texturing": "Teksturowanie", "odm_georeferencing": "Georeferencja",
        "odm_dem": "Model wysokości", "odm_orthophoto": "Ortofotomapa",
        "odm_report": "Raport", "odm_postprocess": "Kończenie",
        "features": "Cechy", "matching": "Dopasowywanie",
        "reconstruction": "Rekonstrukcja", "undistort": "Korekcja dystorsji",
        "remaining": "pozostało", "eta": "koniec o", "of": "z",
    },
    "ru": {
        "dataset": "Подготовка изображений", "split": "Разделение", "merge": "Объединение",
        "opensfm": "Положения камер", "openmvs": "Плотное облако точек",
        "odm_filterpoints": "Фильтрация точек", "odm_meshing": "Полигональная сетка",
        "mvs_texturing": "Текстурирование", "odm_georeferencing": "Геопривязка",
        "odm_dem": "Модель высот", "odm_orthophoto": "Ортофотоплан",
        "odm_report": "Отчёт", "odm_postprocess": "Завершение",
        "features": "Признаки", "matching": "Сопоставление",
        "reconstruction": "Реконструкция", "undistort": "Устранение искажений",
        "remaining": "осталось", "eta": "завершится в", "of": "из",
    },
    "uk": {
        "dataset": "Підготовка зображень", "split": "Розділення", "merge": "Об'єднання",
        "opensfm": "Положення камер", "openmvs": "Щільна хмара точок",
        "odm_filterpoints": "Фільтрація точок", "odm_meshing": "Полігональна сітка",
        "mvs_texturing": "Текстурування", "odm_georeferencing": "Геоприв'язка",
        "odm_dem": "Модель висот", "odm_orthophoto": "Ортофотоплан",
        "odm_report": "Звіт", "odm_postprocess": "Завершення",
        "features": "Ознаки", "matching": "Зіставлення",
        "reconstruction": "Реконструкція", "undistort": "Усунення спотворень",
        "remaining": "залишилось", "eta": "завершиться о", "of": "з",
    },
    "tr": {
        "dataset": "Görüntüler hazırlanıyor", "split": "Bölme", "merge": "Birleştirme",
        "opensfm": "Kamera konumları", "openmvs": "Yoğun nokta bulutu",
        "odm_filterpoints": "Nokta filtreleme", "odm_meshing": "Örgü",
        "mvs_texturing": "Dokulama", "odm_georeferencing": "Coğrafi referanslama",
        "odm_dem": "Yükseklik modeli", "odm_orthophoto": "Ortofoto",
        "odm_report": "Rapor", "odm_postprocess": "Tamamlanıyor",
        "features": "Öznitelikler", "matching": "Eşleştirme",
        "reconstruction": "Yeniden oluşturma", "undistort": "Bozulma düzeltme",
        "remaining": "kalan", "eta": "bitiş", "of": "/",
    },
    "cs": {
        "dataset": "Příprava snímků", "split": "Rozdělení", "merge": "Sloučení",
        "opensfm": "Pozice kamer", "openmvs": "Hustý mrak bodů",
        "odm_filterpoints": "Filtrování bodů", "odm_meshing": "Síť",
        "mvs_texturing": "Texturování", "odm_georeferencing": "Georeferencování",
        "odm_dem": "Výškový model", "odm_orthophoto": "Ortofoto",
        "odm_report": "Zpráva", "odm_postprocess": "Dokončování",
        "features": "Příznaky", "matching": "Párování",
        "reconstruction": "Rekonstrukce", "undistort": "Oprava zkreslení",
        "remaining": "zbývá", "eta": "hotovo v", "of": "z",
    },
    "sv": {
        "dataset": "Förbereder bilder", "split": "Delning", "merge": "Sammanslagning",
        "opensfm": "Kamerapositioner", "openmvs": "Tätt punktmoln",
        "odm_filterpoints": "Filtrerar punkter", "odm_meshing": "Mesh",
        "mvs_texturing": "Texturering", "odm_georeferencing": "Georeferering",
        "odm_dem": "Höjdmodell", "odm_orthophoto": "Ortofoto",
        "odm_report": "Rapport", "odm_postprocess": "Avslutar",
        "features": "Särdrag", "matching": "Matchning",
        "reconstruction": "Rekonstruktion", "undistort": "Korrigerar distorsion",
        "remaining": "återstår", "eta": "klar", "of": "av",
    },
    "el": {
        "dataset": "Προετοιμασία εικόνων", "split": "Διαχωρισμός", "merge": "Συγχώνευση",
        "opensfm": "Θέσεις καμερών", "openmvs": "Πυκνό νέφος σημείων",
        "odm_filterpoints": "Φιλτράρισμα σημείων", "odm_meshing": "Πλέγμα",
        "mvs_texturing": "Υφή", "odm_georeferencing": "Γεωαναφορά",
        "odm_dem": "Μοντέλο υψομέτρου", "odm_orthophoto": "Ορθοφωτογραφία",
        "odm_report": "Αναφορά", "odm_postprocess": "Ολοκλήρωση",
        "features": "Χαρακτηριστικά", "matching": "Αντιστοίχιση",
        "reconstruction": "Ανακατασκευή", "undistort": "Διόρθωση παραμόρφωσης",
        "remaining": "απομένουν", "eta": "τέλος στις", "of": "από",
    },
    "zh-hans": {
        "dataset": "准备图像", "split": "拆分", "merge": "合并",
        "opensfm": "相机位置", "openmvs": "稠密点云",
        "odm_filterpoints": "点云过滤", "odm_meshing": "网格",
        "mvs_texturing": "纹理映射", "odm_georeferencing": "地理配准",
        "odm_dem": "高程模型", "odm_orthophoto": "正射影像",
        "odm_report": "报告", "odm_postprocess": "收尾",
        "features": "特征点", "matching": "特征匹配",
        "reconstruction": "重建", "undistort": "畸变校正",
        "remaining": "剩余", "eta": "预计完成", "of": "/",
    },
    "zh-hant": {
        "dataset": "準備影像", "split": "拆分", "merge": "合併",
        "opensfm": "相機位置", "openmvs": "密集點雲",
        "odm_filterpoints": "點雲過濾", "odm_meshing": "網格",
        "mvs_texturing": "紋理貼圖", "odm_georeferencing": "地理配準",
        "odm_dem": "高程模型", "odm_orthophoto": "正射影像",
        "odm_report": "報告", "odm_postprocess": "收尾",
        "features": "特徵點", "matching": "特徵匹配",
        "reconstruction": "重建", "undistort": "畸變校正",
        "remaining": "剩餘", "eta": "預計完成", "of": "/",
    },
    "ja": {
        "dataset": "画像の準備", "split": "分割", "merge": "統合",
        "opensfm": "カメラ位置", "openmvs": "高密度点群",
        "odm_filterpoints": "点群フィルタ", "odm_meshing": "メッシュ",
        "mvs_texturing": "テクスチャ", "odm_georeferencing": "地理参照",
        "odm_dem": "標高モデル", "odm_orthophoto": "オルソ画像",
        "odm_report": "レポート", "odm_postprocess": "仕上げ",
        "features": "特徴点", "matching": "マッチング",
        "reconstruction": "再構成", "undistort": "歪み補正",
        "remaining": "残り", "eta": "完了予定", "of": "/",
    },
    "ko": {
        "dataset": "이미지 준비", "split": "분할", "merge": "병합",
        "opensfm": "카메라 위치", "openmvs": "고밀도 점군",
        "odm_filterpoints": "점군 필터링", "odm_meshing": "메시",
        "mvs_texturing": "텍스처링", "odm_georeferencing": "지오레퍼런싱",
        "odm_dem": "표고 모델", "odm_orthophoto": "정사영상",
        "odm_report": "보고서", "odm_postprocess": "마무리",
        "features": "특징점", "matching": "매칭",
        "reconstruction": "재구성", "undistort": "왜곡 보정",
        "remaining": "남음", "eta": "완료 예정", "of": "/",
    },
}


def strings(code):
    """Strings for a Django language code, falling back to English.

    Accepts 'pt-br', 'pt_BR', 'pt' and 'zh-hans' alike, and falls back from
    'pt-br' to 'pt' before falling back to English.
    """
    if not code:
        return STRINGS[BASE]
    c = code.lower().replace("_", "-")
    if c in STRINGS:
        return STRINGS[c]
    return STRINGS.get(c.split("-")[0], STRINGS[BASE])

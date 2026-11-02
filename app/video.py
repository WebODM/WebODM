import subprocess
import numpy as np
import logging
from datetime import datetime, timedelta
import re
import os
import sys
from rasterio.warp import transform as rio_transform
from app.geoutils import utm_transformers_from_lonlat, utm_crs_from_lonlat

logger = logging.getLogger('app.logger')

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}

def match_single(regexes, line, dtype=int):
    if isinstance(regexes, str):
        regexes = [(regexes, dtype)]
    
    for i in range(len(regexes)):
        if isinstance(regexes[i], str):
            regexes[i] = (regexes[i], dtype)
    
    try:
        for r, transform in regexes:
            match = re.search(r, line)
            if match:
                res = match.group(1)
                return transform(res)
    except Exception as e:
        logger.warning("Cannot parse SRT line \"%s\": %s" % (line, str(e)))

    return None

class SrtFileParser:
    def __init__(self, filename):
        self.filename = filename
        self.data = []
        self.gps_data = []
        self.ll_to_utm = None
        self.utm_to_ll = None

    def get_entry(self, timestamp):
        if not self.data:
            self.parse()

        # check min and max
        if timestamp < self.data[0]["start"] or timestamp > self.data[len(self.data) - 1]["end"]:
            return None

        for entry in self.data:
            if entry["start"] <= timestamp and entry["end"] >= timestamp:
                return entry

        return None

    def get_gps(self, timestamp):
        if not self.data:
            self.parse()
        
        # Initialize on first call
        prev_coords = None

        if not self.gps_data:
            i = 0
            for d in self.data:
                lat, lon, alt = d.get('latitude'), d.get('longitude'), d.get('altitude')
                if alt is None:
                    alt = 0
                tm = d.get('start')

                if lat is not None and lon is not None:
                    if self.ll_to_utm is None:
                        self.ll_to_utm, self.utm_to_ll = utm_transformers_from_lonlat(lon, lat)

                    coords = self.ll_to_utm(lon, lat, alt)

                    # First or new (in X/Y only) or last
                    add = (not len(self.gps_data)) or (coords[0], coords[1]) != (self.gps_data[-1][1][0], self.gps_data[-1][1][1]) or i == len(self.data) - 1
                    if add:
                        self.gps_data.append((tm, coords))
                i += 1
        
        # No data available
        if not len(self.gps_data) or self.gps_data[0][0] > timestamp:
            return None

        # Interpolate
        start = None
        for i in range(len(self.gps_data)):
            tm, coords = self.gps_data[i]

            # Perfect match
            if timestamp == tm:
                return self.utm_to_ll(*coords)

            elif tm > timestamp:
                end = i
                start = i - 1
                if start < 0:
                    return None

                gd_s = self.gps_data[start]
                gd_e = self.gps_data[end]
                sx, sy, sz = gd_s[1]
                ex, ey, ez = gd_e[1]
                
                dt = (gd_e[0] - gd_s[0]).total_seconds()
                if dt == 0:
                    return None

                dx = (ex - sx) / dt
                dy = (ey - sy) / dt
                dz = (ez - sz) / dt
                t = (timestamp - gd_s[0]).total_seconds()

                return self.utm_to_ll(
                    sx + dx * t,
                    sy + dy * t,
                    sz + dz * t
                )

    def get_linestring(self, resolution=1):
        if not self.data:
            self.parse()

        if not self.data:
            return None, None

        first = self.data[0].get('start')
        last = self.data[-1].get('end')
        if first is None or last is None:
            return None, None

        duration = (last - first).total_seconds()
        if duration <= 0:
            return None, None

        gps_secs = []
        gps_lons = []
        gps_lats = []
        gps_alts = []
        prev_lon = prev_lat = None

        for i, d in enumerate(self.data):
            lat, lon = d.get('latitude'), d.get('longitude')
            alt = d.get('altitude') or 0
            tm = d.get('start')
            if lat is None or lon is None or tm is None:
                continue
            if (lon != prev_lon or lat != prev_lat) or i == len(self.data) - 1:
                gps_secs.append((tm - first).total_seconds())
                gps_lons.append(lon)
                gps_lats.append(lat)
                gps_alts.append(alt)
                prev_lon, prev_lat = lon, lat

        if len(gps_secs) < 2:
            return None, None

        src_crs, dst_crs = utm_crs_from_lonlat(gps_lons[0], gps_lats[0])
        utm_xs, utm_ys = rio_transform(src_crs, dst_crs, gps_lons, gps_lats)

        sample_times = []
        t = 0.0
        while t <= duration:
            sample_times.append(round(t, 3))
            t += resolution
        if round(duration, 3) not in sample_times:
            sample_times.append(round(duration, 3))

        result_x = []
        result_y = []
        result_alt = []
        result_ts = []
        gi = 0
        n = len(gps_secs)

        for st in sample_times:
            if st < gps_secs[0]:
                continue

            while gi < n - 1 and gps_secs[gi + 1] <= st:
                gi += 1

            if gi >= n - 1:
                result_x.append(utm_xs[-1])
                result_y.append(utm_ys[-1])
                result_alt.append(gps_alts[-1])
                result_ts.append(st)
                continue

            dt = gps_secs[gi + 1] - gps_secs[gi]
            if dt == 0:
                result_x.append(utm_xs[gi])
                result_y.append(utm_ys[gi])
                result_alt.append(gps_alts[gi])
            else:
                frac = (st - gps_secs[gi]) / dt
                result_x.append(utm_xs[gi] + frac * (utm_xs[gi + 1] - utm_xs[gi]))
                result_y.append(utm_ys[gi] + frac * (utm_ys[gi + 1] - utm_ys[gi]))
                result_alt.append(gps_alts[gi] + frac * (gps_alts[gi + 1] - gps_alts[gi]))
            result_ts.append(st)

        if len(result_x) < 2:
            return None, None

        out_lons, out_lats = rio_transform(dst_crs, src_crs, result_x, result_y)
        coords = [[out_lons[i], out_lats[i], result_alt[i]] for i in range(len(out_lons))]

        return coords, result_ts

    def parse(self):

        # SRT metadata is not standarized, we support the following formats:

        # DJI mavic air 2
        # 1
        # 00:00:00,000 --> 00:00:00,016
        # <font size="36">SrtCnt : 1, DiffTime : 16ms
        # 2023-01-06 18:56:48,380,821
        # [iso : 3200] [shutter : 1/60.0] [fnum : 280] [ev : 0] [ct : 3925] [color_md : default] [focal_len : 240] [latitude: 0.000000] [longitude: 0.000000] [altitude: 0.000000] </font>
        # </font> 

        # DJI Mavic Mini
        # 1
        # 00:00:00,000 --> 00:00:01,000
        # F/2.8, SS 206.14, ISO 150, EV 0, GPS (-82.6669, 27.7716, 10), D 2.80m, H 0.00m, H.S 0.00m/s, V.S 0.00m/s 

        # DJI Phantom4 RTK
        # 36
        # 00:00:35,000 --> 00:00:36,000
        # F/6.3, SS 60, ISO 100, EV 0, RTK (120.083799, 30.213635, 28), HOME (120.084146, 30.214243, 103.55m), D 75.36m, H 76.19m, H.S 0.30m/s, V.S 0.00m/s, F.PRY (-5.3°, 2.1°, 28.3°), G.PRY (-40.0°, 0.0°, 28.2°)

        # DJI Unknown Model #1
        # 1
        # 00:00:00,000 --> 00:00:00,033
        # <font size="28">SrtCnt : 1, DiffTime : 33ms
        # 2024-01-18 10:23:26.397
        # [iso : 150] [shutter : 1/5000.0] [fnum : 170] [ev : 0] [ct : 5023] [color_md : default] [focal_len : 240] [dzoom_ratio: 10000, delta:0],[latitude: -22.724555] [longitude: -47.602414] [rel_alt: 0.300 abs_alt: 549.679] </font>

        # DJI Mavic 2 Zoom
        # 1
        # 00:00:00,000 --> 00:00:00,041
        # <font size="36">FrameCnt : 1, DiffTime : 41ms
        # 2023-07-15 11:55:16,320,933
        # [iso : 100] [shutter : 1/400.0] [fnum : 280] [ev : 0] [ct : 5818] [color_md : default] [focal_len : 240] [latitude : 0.000000] [longtitude : 0.000000] [altitude: 0.000000] </font>

        # DJI Unknown Model #2
        # 1
        # 00:00:00,000 --> 00:00:00,033
        # No:1, F/2.8, SS 155.55, ISO 100, EV 0, M.M AE_METER_CENTER, A.T (126,109), Luma 106, Coef(1.000000, 1.000000, 1.000000), FaceDetectTag (0), FaceDetectRect (0,0,0,0,), Gain (1.000000,4096), Index (Ev:10085,Nf:0), E.M 0, AERect(n/a), AeAdvScene (GR:91.000000,GWR:1.000000,LLR:0.196683,RR:0.870551), LeCurve(64) (1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,1024,128,), AfSpd 0/0, Af Rect(X:0, Y:0, W:0, H:0), AfPos 0, AwbMode WB_AUTOMATIC, Awb Gain(R:8206, G:4096, B:7058), ColorTemp 5241, B.L (-1020, -1020, -1020, -1020), IQS (39253, 208), ToneInfo (0,16,33,51,68,85,102,119,136,152,169,185,202,218,234,250,266,282,298,314,330,346,362,378,394,410,425,441,457,473,488,500,514,532,550,567,584,602,619,637,654,671,688,705,721,738,754,770,786,801,817,832,847,862,877,892,907,922,937,951,966,981,995,1011,0,64,134,205,274,342,410,477,544,611,677,743,809,873,937,1002,1066,1130,1194,1258,1322,1385,1449,1512,1576,1640,1703,1766,1829,1893,1952,2003,2058,2130,2201,2270,2339,2410,2479,2548,2616,2685,2753,2820,2886,2952,3016,3080,3144,3207,3270,3329,3391,3451,3511,3571,3630,3688,3748,3807,3866,3924,3983,4044,), Isp Info (PIPE 1,ADJ 0,De 0) GPS (-2.5927, 52.0035, 15), D 0.61m, H 1.00m, H.S 0.00m/s, V.S 0.00m/s 


        with open(self.filename, 'r', encoding="utf-8") as f:

            iso = None
            shutter = None
            fnum = None
            focal_len = None
            latitude = None
            longitude = None
            altitude = None
            start = None
            end = None

            for line in f:
                # Remove html tags, spaces
                line = re.sub('<[^<]+?>', '', line).strip()

                if not line:
                    if start is not None:
                        self.data.append({
                            "start": start,
                            "end": end,
                            "iso": iso,
                            "shutter": shutter,
                            "fnum": fnum,
                            "focal_len": focal_len,
                            "latitude": latitude,
                            "longitude": longitude,
                            "altitude": altitude
                        })

                    iso = None
                    shutter = None
                    fnum = None
                    ct = None
                    focal_len = None
                    latitude = None
                    longitude = None
                    altitude = None
                    start = None
                    end = None

                    continue

                # Search this "00:00:00,000 --> 00:00:00,016"
                match = re.search(r"(\d{2}:\d{2}:\d{2},\d+) --> (\d{2}:\d{2}:\d{2},\d+)", line)
                if match:
                    start = datetime.strptime(match.group(1), "%H:%M:%S,%f")
                    end = datetime.strptime(match.group(2), "%H:%M:%S,%f")

                def non_zero_float(v):
                    try:
                        v = float(v)
                        if v == 0:
                            return None
                        return v
                    except ValueError:
                        return None

                iso = match_single([
                    r"iso : (\d+)",
                    r"ISO (\d+)"
                ], line)

                shutter = match_single([
                    (r"shutter : \d+/(\d+\.?\d*)", non_zero_float),
                    (r"SS (\d+\.?\d*)", non_zero_float)
                ], line)

                fnum = match_single([
                    (r"fnum : (\d+)", lambda v: float(v)/100.0),
                    (r"F/([\d\.]+)", float),
                ], line)

                focal_len = match_single(r"focal_len : (\d+)", line)

                latitude = match_single([
                    (r"latitude: ([\d\.\-]+)", non_zero_float),
                    (r"latitude : ([\d\.\-]+)", non_zero_float),
                    (r"GPS \([\d\.\-]+,? ([\d\.\-]+),? [\d\.\-]+\)", non_zero_float),
                    (r"RTK \([-+]?\d+\.\d+, (-?\d+\.\d+), [\d\.\-]+\)", non_zero_float),
                ], line)
                
                longitude = match_single([
                    (r"longitude: ([\d\.\-]+)", non_zero_float),
                    (r"longtitude : ([\d\.\-]+)", non_zero_float),
                    (r"GPS \(([\d\.\-]+),? [\d\.\-]+,? [\d\.\-]+\)", non_zero_float),
                    (r"RTK \((-?\d+\.\d+), [-+]?\d+\.\d+, [\d\.\-]+\)", non_zero_float),
                ], line)
                
                altitude = match_single([
                    (r"altitude: ([\d\.\-]+)", non_zero_float),
                    (r"GPS \([\d\.\-]+,? [\d\.\-]+,? ([\d\.\-]+)\)", non_zero_float),
                    (r"RTK \([-+]?\d+\.\d+, [-+]?\d+\.\d+, ([\d\.\-]+)\)", non_zero_float),
                    (r"abs_alt: ([\d\.\-]+)", non_zero_float),
                ], line)

def extract_gps_from_srt(srt_path):
    try:
        parser = SrtFileParser(srt_path)
        parser.parse()
        return parser.get_gps(datetime(1900, 1, 1))
    except Exception as e:
        logger.warning(f"Cannot extract GPS from {srt_path}: {str(e)}")

def srt_file_for_video(video_path):
    base, ext = os.path.splitext(video_path)
    srt_file = base + '.srt'
    return srt_file

def isfile_case_sensitive(f):
    if sys.platform == 'win32':
        # os.path.isfile on Windows is case insensitive
        if not os.path.isfile(f):
            return False
        return os.path.realpath(f) == os.path.abspath(f)
    else:
        return os.path.isfile(f)

def video_file_for_srt(srt_path):
    base, ext = os.path.splitext(srt_path)
    
    for video_ext in VIDEO_EXTENSIONS:
        video_path = base + video_ext
        if isfile_case_sensitive(video_path):
            return video_path
        
        video_path = base + video_ext.upper()
        if isfile_case_sensitive(video_path):
            return video_path
        
    return None

def extract_subtitles(video_path):
    srt_file = srt_file_for_video(video_path)

    command = [
        'ffmpeg',
        '-i', video_path,
        '-map', '0:s:0',
        srt_file,
        '-y',
        '-hide_banner',
        '-loglevel', 'quiet'
    ]

    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        process.communicate(timeout=15)
    except Exception as e:
        process.kill()
        process.communicate()
        logger.warning(f"Error: ffmpeg error while extracting subs from {video_path}: {str(e)}")

    return isfile_case_sensitive(srt_file)

def extract_jpeg_bytes_from_video(video_path, width=256, timestamp="00:00:01", quality=4):
    command = [
        'ffmpeg',
        '-ss', timestamp,
        '-i', video_path,
        '-vf', f'scale={width}:-1',
        '-frames:v', '1',
        '-f', 'image2',
        '-vcodec', 'mjpeg',
        '-q:v', str(quality), # Quality scale (1-31)
        '-loglevel', 'quiet',
        'pipe:1', # output to stdout
    ]

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        outbytes, err = process.communicate(timeout=15)
    except Exception as e:
        process.kill()
        outbytes, err = process.communicate()
        logger.warning(f"Error: ffmpeg error while reading {video_path}: {str(e)}")
        return None

    if not outbytes:
        return None
    
    return outbytes

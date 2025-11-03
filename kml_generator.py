"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import pandas as pd
import math
import textwrap
import re
from datetime import datetime, timedelta
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal


class KMLGenerator(QThread):
    """Background thread for KML generation"""
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)  # KML content
    error = pyqtSignal(str)     # error message
    status_message = pyqtSignal(str)  # status messages for console
    
    def __init__(self, data_file, data_type, settings):
        super().__init__()
        self.data_file = data_file
        self.data_type = data_type
        self.settings = settings
    
    def run(self):
        try:
            # Load data
            self.progress.emit(10)
            
            # Read file based on extension (with Excel date handling)
            file_extension = Path(self.data_file).suffix.lower()
            if file_extension == '.xlsx':
                # Read Excel with proper date parsing
                df = pd.read_excel(self.data_file, engine='openpyxl')
            elif file_extension == '.csv':
                df = pd.read_csv(self.data_file)
            else:
                raise ValueError(f"Unsupported file format: {file_extension}")
            
            # Generate KML based on data type
            self.progress.emit(30)
            if self.data_type == "Tower/Sector":
                kml_content = self.generate_cell_tower_kml(df)
            elif self.data_type == "Distance from Tower":
                kml_content = self.generate_timing_advance_kml(df)
            elif self.data_type == "Location Point":
                kml_content = self.generate_gps_kml(df)
            else:
                raise ValueError(f"Unknown data type: {self.data_type}")
            
            self.progress.emit(100)
            self.finished.emit(kml_content)
            
        except Exception as e:
            self.error.emit(str(e))
    
    def destination_point(self, lat, lon, azimuth_deg, distance_miles):
        """Calculate destination point given starting point, bearing and distance"""
        R = 3960.0  # Earth radius in miles
        azimuth = math.radians(azimuth_deg)
        lat1 = math.radians(lat)
        lon1 = math.radians(lon)
        d_div_r = distance_miles / R

        if d_div_r < 1e-9:
            return lat, lon

        lat2 = math.asin(math.sin(lat1) * math.cos(d_div_r) +
                         math.cos(lat1) * math.sin(d_div_r) * math.cos(azimuth))
        lon2 = lon1 + math.atan2(math.sin(azimuth) * math.sin(d_div_r) * math.cos(lat1),
                                 math.cos(d_div_r) - math.sin(lat1) * math.sin(lat2))
        return math.degrees(lat2), math.degrees(lon2)
    
    def generate_cell_tower_kml(self, df):
        """Generate KML for tower/sector data"""
        # Use custom label if provided, otherwise default
        doc_name = self.settings.get('custom_label') or "Tower/Sector Data"
        
        kml_header = textwrap.dedent(f'''\
            <?xml version="1.0" encoding="UTF-8"?>
            <kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">
            <Document>
                <name>{doc_name}</name>
                <gx:AnimatedUpdate>
                    <gx:duration>0.0</gx:duration>
                </gx:AnimatedUpdate>
        ''')
        
        kml_footer = textwrap.dedent('''\
            </Document>
            </kml>
        ''')
        
        placemarks = ""
        total_rows = len(df)
        missing_azimuth_count = 0
        
        for idx, (_, row) in enumerate(df.iterrows()):
            if idx % 10 == 0:  # Update progress every 10 rows
                progress = 30 + int((idx / total_rows) * 50)
                self.progress.emit(progress)
            
            # Get required columns
            lat = self.get_column_value(row, ['Latitude', 'lat', 'Lat'])
            lon = self.get_column_value(row, ['Longitude', 'lon', 'Lon', 'Long'])
            timestamp = self.get_column_value(row, ['Timestamp', 'Date & Time', 'DateTime', 'Time'])
            azimuth = self.get_column_value(row, ['Azimuth', 'azimuth', 'bearing', 'direction'])
            
            if pd.isna(lat) or pd.isna(lon):
                continue
            
            # Use timestamp if available, otherwise use a generic label
            if pd.isna(timestamp):
                timestamp = f"Entry {idx + 1}"
            
            # Generate sector or circle based on azimuth availability
            if not pd.isna(azimuth):
                placemarks += self.create_sector_placemark(lat, lon, azimuth, timestamp)
            else:
                missing_azimuth_count += 1
                # Create 360-degree circle instead of directional wedge
                placemarks += self.create_circle_placemark(lat, lon, timestamp)
        
        # Report missing azimuth data
        if missing_azimuth_count > 0:
            self.status_message.emit(f"⚠️ Tower/Sector Data: {missing_azimuth_count} points had no azimuth data - used 360° coverage circles")
        
        return kml_header + placemarks + kml_footer
    
    def generate_timing_advance_kml(self, df):
        """Generate KML for distance from tower data with arc visualization"""
        # Use custom label if provided, otherwise default
        doc_name = self.settings.get('custom_label') or "Distance from Tower Analysis"
        
        kml_header = textwrap.dedent(f'''\
            <?xml version="1.0" encoding="UTF-8"?>
            <kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">
            <Document>
                <name>{doc_name}</name>
                <gx:AnimatedUpdate>
                    <gx:duration>0.0</gx:duration>
                </gx:AnimatedUpdate>
        ''')
        
        kml_footer = textwrap.dedent('''\
            </Document>
            </kml>
        ''')
        
        placemarks = ""
        total_rows = len(df)
        missing_azimuth_count = 0
        missing_distance_count = 0
        
        for idx, (_, row) in enumerate(df.iterrows()):
            if idx % 10 == 0:
                progress = 30 + int((idx / total_rows) * 50)
                self.progress.emit(progress)
            
            lat = self.get_column_value(row, ['Latitude', 'lat', 'Lat'])
            lon = self.get_column_value(row, ['Longitude', 'lon', 'Lon', 'Long'])
            timestamp = self.get_column_value(row, ['Timestamp', 'Date & Time', 'DateTime', 'Time'])
            azimuth = self.get_column_value(row, ['Azimuth', 'bearing', 'direction'])
            distance = self.get_column_value(row, ['Distance', 'range', 'distance (m)', 'distance (meters)'])
            
            if pd.isna(lat) or pd.isna(lon):
                continue
            
            # Use timestamp if available, otherwise use a generic label
            if pd.isna(timestamp):
                timestamp = f"Entry {idx + 1}"
            
            # Determine visualization based on available data
            has_azimuth = not pd.isna(azimuth)
            has_distance = not pd.isna(distance)
            
            if has_azimuth and has_distance:
                # Case 1: Has both azimuth and distance - create combined tower/sector + distance arc visualization
                distance_miles = self.convert_ta_distance_to_miles(distance, self.settings.get('ta_distance_units', 'Meters'))
                placemarks += self.create_combined_sector_and_arc(lat, lon, azimuth, timestamp, distance_miles)
                
            elif has_azimuth and not has_distance:
                # Case 2: Has azimuth but missing distance - create directional wedge
                missing_distance_count += 1
                placemarks += self.create_sector_placemark(lat, lon, azimuth, timestamp)
                
            elif not has_azimuth and has_distance:
                # Case 3: Missing azimuth but has distance - create 360° circle at the distance
                missing_azimuth_count += 1
                distance_miles = self.convert_ta_distance_to_miles(distance, self.settings.get('ta_distance_units', 'Meters'))
                placemarks += self.create_distance_circle(lat, lon, timestamp, distance_miles)
                
            else:
                # Case 4: Missing both azimuth and distance - create 360° circle using shaded area length
                missing_azimuth_count += 1
                missing_distance_count += 1
                placemarks += self.create_circle_placemark(lat, lon, timestamp)
        
        # Report missing data
        if missing_azimuth_count > 0:
            self.status_message.emit(f"⚠️ Distance from Tower Data: {missing_azimuth_count} points had no azimuth data - used 360° coverage areas")
        if missing_distance_count > 0:
            self.status_message.emit(f"⚠️ Distance from Tower Data: {missing_distance_count} points had no distance data - distance from tower not drawn")

        return kml_header + placemarks + kml_footer
    
    def generate_gps_kml(self, df):
        """Generate KML for location point data"""
        # Use custom label if provided, otherwise default
        doc_name = self.settings.get('custom_label') or "Location Point Data"
        
        kml_header = textwrap.dedent(f'''\
            <?xml version="1.0" encoding="UTF-8"?>
            <kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">
            <Document>
                <name>{doc_name}</name>
                <gx:AnimatedUpdate>
                    <gx:duration>0.0</gx:duration>
                </gx:AnimatedUpdate>
        ''')
        
        kml_footer = textwrap.dedent('''\
            </Document>
            </kml>
        ''')
        
        placemarks = ""
        total_rows = len(df)
        missing_accuracy_count = 0
        
        for idx, (_, row) in enumerate(df.iterrows()):
            if idx % 10 == 0:
                progress = 30 + int((idx / total_rows) * 50)
                self.progress.emit(progress)
            
            lat = self.get_column_value(row, ['Latitude', 'lat', 'Lat'])
            lon = self.get_column_value(row, ['Longitude', 'lon', 'Lon', 'Long'])
            timestamp = self.get_column_value(row, ['Timestamp', 'Date & Time', 'DateTime', 'Time'])
            gps_accuracy = self.get_column_value(row, ['GPS Accuracy', 'Accuracy', 'gps_accuracy', 'accuracy'])
            
            if pd.isna(lat) or pd.isna(lon) or pd.isna(timestamp):
                continue
            
            # Convert location point accuracy to miles for consistent circle size
            if pd.isna(gps_accuracy):
                missing_accuracy_count += 1
                # Use configurable default radius from settings with proper units
                default_accuracy = self.settings.get('default_accuracy', 100)
                default_units = self.settings.get('gps_units', 'Meters')
                radius_miles = self.convert_gps_accuracy_to_miles(default_accuracy, default_units)
            else:
                radius_miles = self.convert_gps_accuracy_to_miles(gps_accuracy, self.settings.get('gps_units', 'Meters'))
            
            # Create location point accuracy circle
            placemarks += self.create_gps_accuracy_circle(lat, lon, timestamp, radius_miles)
        
        # Report missing accuracy data
        if missing_accuracy_count > 0:
            default_accuracy = self.settings.get('default_accuracy', 100)
            default_units = self.settings.get('gps_units', 'Meters')
            self.status_message.emit(f"⚠️ Location Point Data: {missing_accuracy_count} points had no accuracy data - used {default_accuracy} {default_units.lower()} default radius")
        
        return kml_header + placemarks + kml_footer
    
    def convert_gps_accuracy_to_miles(self, accuracy_value, units):
        """Convert location point accuracy from various units to miles"""
        try:
            accuracy_float = float(accuracy_value)
            
            if units == "Meters":
                return accuracy_float * 0.000621371  # meters to miles
            elif units == "Feet":
                return accuracy_float * 0.000189394  # feet to miles
            elif units == "Miles":
                return accuracy_float  # already in miles
            elif units == "Kilometers":
                return accuracy_float * 0.621371  # kilometers to miles
            else:
                # Default to meters if unknown unit
                return accuracy_float * 0.000621371
        except (ValueError, TypeError):
            # If conversion fails, return a small default radius (10 meters in miles)
            return 10 * 0.000621371
    
    def create_gps_accuracy_circle(self, lat, lon, timestamp, radius_miles):
        """Create a location point accuracy circle using the location point color"""
        kml_timestamp, display_label = self.parse_timestamp_to_kml(timestamp)
        
        # Create folder to group circle and timestamp label
        placemark = textwrap.dedent(f'''\
            <Folder>
                <name>{display_label}</name>
        ''')
        
        # Add timestamp if successfully interpreted
        placemark += self.create_time_element(kml_timestamp)
        
        # 1. Create location point accuracy circle
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label} Location Point Circle</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <LineStyle>
                            <color>{self.settings['gps_color']}</color>
                            <width>2</width>
                        </LineStyle>
                        <PolyStyle>
                            <color>4d{self.settings['gps_color'][2:]}</color>
                        </PolyStyle>
                    </Style>
                    <Polygon>
                        <outerBoundaryIs>
                            <LinearRing>
                                <coordinates>
        ''')
        
        # Generate circle points
        for i in range(37):  # 36 points + close the loop
            angle = i * 10  # Every 10 degrees
            circle_lat, circle_lon = self.destination_point(lat, lon, angle, radius_miles)
            placemark += f"                    {circle_lon},{circle_lat},0\n"
        
        placemark += textwrap.dedent('''\
                                </coordinates>
                            </LinearRing>
                        </outerBoundaryIs>
                    </Polygon>
                </Placemark>
        ''')
        
        # 2. Add invisible center point label to show timestamp
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label}</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <IconStyle>
                            <scale>0</scale>
                        </IconStyle>
                        <LabelStyle>
                            <color>ffffffff</color>
                            <scale>0.8</scale>
                        </LabelStyle>
                    </Style>
                    <Point>
                        <coordinates>{lon},{lat},0</coordinates>
                    </Point>
                </Placemark>
            </Folder>
        ''')
        
        return placemark
    
    def get_column_value(self, row, possible_names):
        """Get value from row using flexible column naming"""
        for name in possible_names:
            if name in row.index and not pd.isna(row[name]):
                return row[name]
        return None
    
    def parse_timestamp_to_kml(self, timestamp_str):
        """Parse various timestamp formats and convert to KML-compatible format"""
        if pd.isna(timestamp_str) or not timestamp_str or str(timestamp_str).strip() == '' or str(timestamp_str).lower() == 'none':
            return None, str(timestamp_str) if timestamp_str and str(timestamp_str).lower() != 'none' else "Unknown"
        
        timestamp_str = str(timestamp_str).strip()
        
        # Try Excel serial date format first (numeric value like 45696.7637037037)
        try:
            timestamp_float = float(timestamp_str)
            # Excel serial dates are stored as days since 1900-01-01
            # Check if it's a reasonable Excel serial (between 1 and ~50000, which covers years 1900-2037)
            if 1 < timestamp_float < 50000:
                excel_epoch = datetime(1900, 1, 1)
                # Excel has a leap year bug - day 60 doesn't exist (Feb 29, 1900)
                days_offset = int(timestamp_float)
                if days_offset > 59:  # After the non-existent Feb 29, 1900
                    days_offset -= 1
                fractional_day = timestamp_float - int(timestamp_float)
                dt = excel_epoch + timedelta(days=days_offset, seconds=fractional_day * 86400)
                kml_timestamp = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
                display_label = dt.strftime('%Y-%m-%d %H:%M:%S')
                return kml_timestamp, display_label
        except (ValueError, OverflowError):
            pass
        
        # Strip timezone info from timestamps (e.g., "(GMT -4)", "(GMT+0)", "EST", "UTC")
        # Remove patterns like (GMT±X), (UTC±X), timezone abbreviations at end
        timestamp_str_clean = re.sub(r'\s*\([^)]*GMT[^)]*\)', '', timestamp_str)  # (GMT -4) style
        timestamp_str_clean = re.sub(r'\s*\([^)]*UTC[^)]*\)', '', timestamp_str_clean)  # (UTC±X) style
        timestamp_str_clean = re.sub(r'\s+[A-Z]{3,4}(?:\s|$)', ' ', timestamp_str_clean)  # EST, UTC, GMT suffix
        timestamp_str_clean = timestamp_str_clean.strip()
        
        # Strip milliseconds and microseconds (e.g., "2025-02-11 11:06:07.557" -> "2025-02-11 11:06:07")
        timestamp_str_clean = re.sub(r'(\d{2}):(\d{2}):(\d{2})\.\d+', r'\1:\2:\3', timestamp_str_clean)
        
        # Common timestamp patterns
        patterns = [
            # ISO format variations
            r'(\d{4})-(\d{1,2})-(\d{1,2})[T\s](\d{1,2}):(\d{1,2}):(\d{1,2})',
            r'(\d{4})-(\d{1,2})-(\d{1,2})[T\s](\d{1,2}):(\d{1,2})',
            r'(\d{4})-(\d{1,2})-(\d{1,2})',
            # ISO forward-slash format (2025/02/03 18:36:04)
            r'(\d{4})/(\d{1,2})/(\d{1,2})[T\s](\d{1,2}):(\d{1,2}):(\d{1,2})',
            r'(\d{4})/(\d{1,2})/(\d{1,2})[T\s](\d{1,2}):(\d{1,2})',
            r'(\d{4})/(\d{1,2})/(\d{1,2})',
            # US format variations (with 4-digit years)
            r'(\d{1,2})/(\d{1,2})/(\d{4})[T\s](\d{1,2}):(\d{1,2}):(\d{1,2})',
            r'(\d{1,2})/(\d{1,2})/(\d{4})[T\s](\d{1,2}):(\d{1,2})',
            r'(\d{1,2})/(\d{1,2})/(\d{4})',
            # US format with 2-digit years (07/30/24 13:00:20)
            r'(\d{1,2})/(\d{1,2})/(\d{2})[T\s](\d{1,2}):(\d{1,2}):(\d{1,2})',
            r'(\d{1,2})/(\d{1,2})/(\d{2})[T\s](\d{1,2}):(\d{1,2})',
            r'(\d{1,2})/(\d{1,2})/(\d{2})',
            # European format variations (DD.MM.YYYY)
            r'(\d{1,2})\.(\d{1,2})\.(\d{4})[T\s](\d{1,2}):(\d{1,2}):(\d{1,2})',
            r'(\d{1,2})\.(\d{1,2})\.(\d{4})[T\s](\d{1,2}):(\d{1,2})',
            r'(\d{1,2})\.(\d{1,2})\.(\d{4})',
            # Time-only patterns (use today's date)
            r'(\d{1,2}):(\d{1,2}):(\d{1,2})\s*([APap][Mm])?',
            r'(\d{1,2}):(\d{1,2})\s*([APap][Mm])?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, timestamp_str_clean)
            if match:
                groups = match.groups()
                
                try:
                    # Check if this is a time-only pattern
                    if ':' in timestamp_str_clean and not any(char in timestamp_str_clean for char in ['/', '-', '.']):
                        # Time-only format - use today's date
                        hour = int(groups[0])
                        minute = int(groups[1])
                        second = int(groups[2]) if len(groups) > 2 and groups[2] else 0
                        
                        # Handle AM/PM
                        is_time_only = True
                        if len(groups) > 2 and groups[-1] and groups[-1].lower() in ['pm', 'am']:
                            if groups[-1].lower() == 'pm' and hour != 12:
                                hour += 12
                            elif groups[-1].lower() == 'am' and hour == 12:
                                hour = 0
                        
                        # Use today's date for time-only entries
                        today = datetime.now()
                        dt = datetime(today.year, today.month, today.day, hour, minute, second)
                        is_time_only = True
                        
                    else:
                        is_time_only = False
                        # Handle different date formats
                        if '/' in timestamp_str_clean:  # US or ISO forward-slash format MM/DD/YYYY or YYYY/MM/DD
                            # Determine if it's US (MM/DD/YYYY) or ISO (YYYY/MM/DD) based on first number
                            first_num = int(groups[0])
                            if first_num > 31:  # Must be YYYY, ISO format
                                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                            else:  # US format MM/DD/YYYY
                                month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                        elif '.' in timestamp_str_clean:  # European format DD.MM.YYYY
                            day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
                        else:  # ISO format YYYY-MM-DD
                            year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                        
                        # Handle 2-digit years (convert to 4-digit)
                        if year < 100:
                            # Assume 00-30 is 2000-2030, 31-99 is 1931-1999
                            year = 2000 + year if year <= 30 else 1900 + year
                        
                        # Handle time if present
                        hour = int(groups[3]) if len(groups) > 3 else 0
                        minute = int(groups[4]) if len(groups) > 4 else 0
                        second = int(groups[5]) if len(groups) > 5 else 0
                        
                        # Create datetime object
                        dt = datetime(year, month, day, hour, minute, second)
                    
                    # Format for KML (ISO 8601)
                    kml_timestamp = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
                    
                    # Create display label - show only time for time-only entries
                    if is_time_only:
                        # For time-only entries, show just the time in a clean format
                        if len(groups) > 3 and groups[-1] and groups[-1].lower() in ['pm', 'am']:
                            # Keep AM/PM format if it was in the original
                            display_label = dt.strftime('%I:%M:%S %p').lstrip('0')
                        else:
                            # Use 24-hour format
                            display_label = dt.strftime('%H:%M:%S')
                    else:
                        # For full timestamps, show date and time
                        display_label = dt.strftime('%Y-%m-%d %H:%M:%S')
                    
                    return kml_timestamp, display_label
                    
                except (ValueError, OverflowError):
                    continue
        
        # If no pattern matches, return None for KML timestamp but keep original as label
        return None, timestamp_str
    
    def calculate_end_timestamp(self, kml_timestamp, duration_minutes):
        """Calculate end timestamp by adding duration to the begin timestamp"""
        try:
            # Parse the KML timestamp (ISO format: YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD)
            if 'T' in kml_timestamp:
                # Full datetime
                dt = datetime.fromisoformat(kml_timestamp.replace('Z', ''))
            else:
                # Date only - assume start of day
                dt = datetime.fromisoformat(kml_timestamp + 'T00:00:00')
            
            # Add duration
            end_dt = dt + timedelta(minutes=duration_minutes)
            
            # Return in KML format
            if 'T' in kml_timestamp:
                return end_dt.isoformat()
            else:
                # If original was date-only, return date-only for end as well
                return end_dt.strftime('%Y-%m-%d')
                
        except (ValueError, TypeError) as e:
            # If parsing fails, return None to fall back to begin-only
            return None
    
    def create_time_element(self, kml_timestamp, indent="        "):
        """Create a TimeSpan element with begin and end times for duration-based animation"""
        if not kml_timestamp or not self.settings.get('enable_time_animation', True):
            return ""
        
        # Calculate end time based on duration setting
        duration_minutes = self.settings.get('duration_minutes', 30)
        end_timestamp = self.calculate_end_timestamp(kml_timestamp, duration_minutes)
        
        if end_timestamp:
            # Use gx:TimeSpan with both begin and end for duration-based visibility
            return f"{indent}<gx:TimeSpan><begin>{kml_timestamp}</begin><end>{end_timestamp}</end></gx:TimeSpan>\n"
        else:
            # Fallback to begin-only if end calculation fails
            return f"{indent}<gx:TimeSpan><begin>{kml_timestamp}</begin></gx:TimeSpan>\n"
    
    def create_sector_placemark(self, lat, lon, azimuth, timestamp):
        """Create a sector wedge placemark with extended directional lines (SWGDE style)"""
        kml_timestamp, display_label = self.parse_timestamp_to_kml(timestamp)
        
        start_angle = azimuth - self.settings['azimuth_spread'] / 2
        end_angle = azimuth + self.settings['azimuth_spread'] / 2
        
        # Create folder to group sector and extended lines
        placemark = textwrap.dedent(f'''\
            <Folder>
                <name>{display_label}</name>
        ''')
        
        # Add timestamp if successfully interpreted and time animation is enabled
        placemark += self.create_time_element(kml_timestamp)
        
        # 1. Create the shaded sector wedge
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label} Shaded Area</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <LineStyle><color>{self.settings['leg_color']}</color><width>1</width></LineStyle>
                        <PolyStyle><color>7d{self.settings['shaded_color'][2:]}</color></PolyStyle>
                    </Style>
                    <Polygon>
                        <outerBoundaryIs><LinearRing><coordinates>
                            {lon},{lat},0
        ''')
        
        # Generate arc points for shaded area
        for i in range(self.settings['num_points'] + 1):
            angle = start_angle + (end_angle - start_angle) * i / self.settings['num_points']
            arc_lat, arc_lon = self.destination_point(lat, lon, angle, self.settings['shaded_area_length'])
            placemark += f"                {arc_lon},{arc_lat},0\n"
        
        placemark += f"                {lon},{lat},0\n"
        placemark += textwrap.dedent('''\
                        </coordinates></LinearRing></outerBoundaryIs>
                    </Polygon>
                </Placemark>
        ''')
        
        # 2. Create center point label (no icon, just show timestamp)
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label}</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <IconStyle>
                            <scale>0</scale>
                        </IconStyle>
                        <LabelStyle>
                            <color>ffffffff</color>
                            <scale>0.8</scale>
                        </LabelStyle>
                    </Style>
                    <Point>
                        <coordinates>{lon},{lat},0</coordinates>
                    </Point>
                </Placemark>
        ''')
        
        # 3. Create extended directional lines (legs)
        leg_length = self.settings['leg_length']
        
        # Left directional line
        left_lat, left_lon = self.destination_point(lat, lon, start_angle, leg_length)
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label} Left Leg</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <LineStyle><color>{self.settings['leg_color']}</color><width>2</width></LineStyle>
                    </Style>
                    <LineString>
                        <coordinates>
                            {lon},{lat},0
                            {left_lon},{left_lat},0
                        </coordinates>
                    </LineString>
                </Placemark>
        ''')
        
        # Right directional line
        right_lat, right_lon = self.destination_point(lat, lon, end_angle, leg_length)
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label} Right Leg</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <LineStyle><color>{self.settings['leg_color']}</color><width>2</width></LineStyle>
                    </Style>
                    <LineString>
                        <coordinates>
                            {lon},{lat},0
                            {right_lon},{right_lat},0
                        </coordinates>
                    </LineString>
                </Placemark>
            </Folder>
        ''')
        
        return placemark
    
    def create_circle_placemark(self, lat, lon, timestamp):
        """Create a circular visualization placemark"""
        kml_timestamp, display_label = self.parse_timestamp_to_kml(timestamp)
        
        # Create folder to group circle and center label
        placemark = textwrap.dedent(f'''\
            <Folder>
                <name>{display_label}</name>
        ''')
        
        # Add timestamp if successfully parsed and time animation is enabled
        placemark += self.create_time_element(kml_timestamp)
        
        # 1. Create the circle
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label} Visualization Area</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <LineStyle><color>{self.settings['leg_color']}</color><width>1</width></LineStyle>
                        <PolyStyle><color>7d{self.settings['shaded_color'][2:]}</color></PolyStyle>
                    </Style>
                    <Polygon>
                        <outerBoundaryIs><LinearRing><coordinates>
        ''')
        
        # Generate circle points
        for i in range(37):  # 0 to 360 degrees, every 10 degrees
            angle = i * 10
            arc_lat, arc_lon = self.destination_point(lat, lon, angle, self.settings['shaded_area_length'])
            placemark += f"                            {arc_lon},{arc_lat},0\n"
        
        placemark += textwrap.dedent(f'''\
                        </coordinates></LinearRing></outerBoundaryIs>
                    </Polygon>
                </Placemark>
        
                <Placemark>
                    <name>{display_label}</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <IconStyle>
                            <scale>0</scale>
                        </IconStyle>
                        <LabelStyle>
                            <color>ffffffff</color>
                            <scale>0.8</scale>
                        </LabelStyle>
                    </Style>
                    <Point>
                        <coordinates>{lon},{lat},0</coordinates>
                    </Point>
                </Placemark>
            </Folder>
        ''')
        
        return placemark
    
    def create_uncertainty_circle(self, lat, lon, timestamp, radius_miles):
        """Create uncertainty circle for distance from tower data"""
        kml_timestamp, display_label = self.parse_timestamp_to_kml(timestamp)
        
        placemark = textwrap.dedent(f'''\
            <Placemark>
                <name>{display_label} Uncertainty</name>
        ''')
        
        # Add timestamp if successfully interpreted and time animation is enabled
        placemark += self.create_time_element(kml_timestamp)
        
        placemark += textwrap.dedent(f'''\
                <Style>
                    <LineStyle><color>{self.settings['ta_color']}</color><width>1</width></LineStyle>
                    <PolyStyle><color>7d{self.settings['ta_color'][2:]}</color></PolyStyle>
                </Style>
                <Polygon>
                    <outerBoundaryIs><LinearRing><coordinates>
        ''')
        
        # Generate circle points
        for i in range(37):
            angle = i * 10
            arc_lat, arc_lon = self.destination_point(lat, lon, angle, radius_miles)
            placemark += f"{arc_lon},{arc_lat},0\n"
        
        placemark += f"{lon},{lat},0\n"
        placemark += textwrap.dedent('''\
                    </coordinates></LinearRing></outerBoundaryIs>
                </Polygon>
            </Placemark>
        ''')
        
        return placemark
    
    def create_pin_placemark(self, lat, lon, name, color):
        """Create a pin placemark"""
        kml_timestamp, display_label = self.parse_timestamp_to_kml(name)
        
        placemark = textwrap.dedent(f'''\
            <Placemark>
                <name>{display_label}</name>
        ''')
        
        # Add timestamp if successfully interpreted and time animation is enabled
        placemark += self.create_time_element(kml_timestamp)
        
        placemark += textwrap.dedent(f'''\
                <Style><IconStyle><color>{color}</color></IconStyle></Style>
                <Point>
                    <coordinates>{lon},{lat},0</coordinates>
                </Point>
            </Placemark>
        ''')
        
        return placemark
    
    def create_combined_sector_and_arc(self, lat, lon, azimuth, timestamp, distance_miles):
        """Create combined tower/sector visualization with distance arc in a single folder"""
        kml_timestamp, display_label = self.parse_timestamp_to_kml(timestamp)
        
        # Get settings
        azimuth_spread = self.settings.get('azimuth_spread', 120)
        half_spread = azimuth_spread / 2
        leg_length = self.settings.get('leg_length', 3.0)
        shaded_area_length = self.settings.get('shaded_area_length', 1.0)
        
        # Calculate start and end angles for the sector
        start_angle = azimuth - half_spread
        end_angle = azimuth + half_spread
        
        # Create single folder for both sector and arc
        placemark = textwrap.dedent(f'''\
            <Folder>
                <name>{display_label}</name>
        ''')
        
        # Add timestamp for time animation
        placemark += self.create_time_element(kml_timestamp)
        
        # 1. Create the shaded sector wedge
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label} Tower Sector</name>
                    <description>
                        Tower: {lat:.6f}, {lon:.6f}
                        Azimuth: {azimuth}°
                        Sector Width: {azimuth_spread}°
                        Distance: {distance_miles:.2f} miles
                    </description>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <LineStyle><color>{self.settings['leg_color']}</color><width>1</width></LineStyle>
                        <PolyStyle><color>7d{self.settings['shaded_color'][2:]}</color></PolyStyle>
                    </Style>
                    <Polygon>
                        <outerBoundaryIs>
                            <LinearRing>
                                <coordinates>
                                    {lon},{lat},0
        ''')
        
        # Generate arc points for the sector wedge
        num_points = self.settings.get('num_points', 20)
        for i in range(num_points + 1):
            angle = start_angle + (i / num_points) * azimuth_spread
            arc_lat, arc_lon = self.destination_point(lat, lon, angle, shaded_area_length)
            placemark += f"                                    {arc_lon},{arc_lat},0\n"
        
        placemark += textwrap.dedent(f'''\
                                    {lon},{lat},0
                                </coordinates>
                            </LinearRing>
                        </outerBoundaryIs>
                    </Polygon>
                </Placemark>
        ''')
        
        # 2. Create left directional line
        left_lat, left_lon = self.destination_point(lat, lon, start_angle, leg_length)
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label} Left Leg</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <LineStyle><color>{self.settings['leg_color']}</color><width>2</width></LineStyle>
                    </Style>
                    <LineString>
                        <coordinates>
                            {lon},{lat},0
                            {left_lon},{left_lat},0
                        </coordinates>
                    </LineString>
                </Placemark>
        ''')
        
        # 3. Create right directional line
        right_lat, right_lon = self.destination_point(lat, lon, end_angle, leg_length)
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label} Right Leg</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <LineStyle><color>{self.settings['leg_color']}</color><width>2</width></LineStyle>
                    </Style>
                    <LineString>
                        <coordinates>
                            {lon},{lat},0
                            {right_lon},{right_lat},0
                        </coordinates>
                    </LineString>
                </Placemark>
        ''')
        
        # 4. Create the distance arc
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label} Distance Arc ({distance_miles:.2f} mi)</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <LineStyle><color>{self.settings['ta_color']}</color><width>3</width></LineStyle>
                    </Style>
                    <LineString>
                        <coordinates>
        ''')
        
        # Generate arc points for the distance arc
        for i in range(num_points + 1):
            angle = start_angle + (i / num_points) * azimuth_spread
            arc_lat, arc_lon = self.destination_point(lat, lon, angle, distance_miles)
            placemark += f"                            {arc_lon},{arc_lat},0\n"
        
        placemark += textwrap.dedent('''\
                        </coordinates>
                    </LineString>
                </Placemark>
        ''')
        
        # 5. Add invisible center point label to show timestamp
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label}</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <IconStyle>
                            <scale>0</scale>
                        </IconStyle>
                        <LabelStyle>
                            <color>ffffffff</color>
                            <scale>0.8</scale>
                        </LabelStyle>
                    </Style>
                    <Point>
                        <coordinates>{lon},{lat},0</coordinates>
                    </Point>
                </Placemark>
            </Folder>
        ''')
        
        return placemark
    
    def create_distance_circle(self, lat, lon, timestamp, distance_miles):
        """Create a circle at the distance from tower (when azimuth is missing)"""
        kml_timestamp, display_label = self.parse_timestamp_to_kml(timestamp)
        
        # Create folder to group circle and center label
        placemark = textwrap.dedent(f'''\
            <Folder>
                <name>{display_label} Distance Circle</name>
        ''')
        
        # Add timestamp if successfully interpreted and time animation is enabled
        placemark += self.create_time_element(kml_timestamp)
        
        # Create the circle at the distance
        placemark += textwrap.dedent(f'''\
                <Placemark>
                    <name>{display_label} Distance Circle ({distance_miles:.2f} mi)</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <LineStyle><color>{self.settings['ta_color']}</color><width>3</width></LineStyle>
                    </Style>
                    <LineString>
                        <coordinates>
        ''')
        
        # Generate circle points at the distance
        for i in range(37):  # 0 to 360 degrees, every 10 degrees
            angle = i * 10
            arc_lat, arc_lon = self.destination_point(lat, lon, angle, distance_miles)
            placemark += f"                            {arc_lon},{arc_lat},0\n"
        
        placemark += textwrap.dedent(f'''\
                        </coordinates>
                    </LineString>
                </Placemark>
        
                <Placemark>
                    <name>{display_label}</name>
        ''')
        
        placemark += self.create_time_element(kml_timestamp, "            ")
        
        placemark += textwrap.dedent(f'''\
                    <Style>
                        <IconStyle>
                            <scale>0</scale>
                        </IconStyle>
                        <LabelStyle>
                            <color>ffffffff</color>
                            <scale>0.8</scale>
                        </LabelStyle>
                    </Style>
                    <Point>
                        <coordinates>{lon},{lat},0</coordinates>
                    </Point>
                </Placemark>
            </Folder>
        ''')
        
        return placemark
    
    def convert_ta_distance_to_miles(self, distance, units):
        """Convert distance from tower distance to miles based on user-selected units"""
        if units == "Meters":
            return distance / 1609.34  # meters to miles
        elif units == "Feet":
            return distance / 5280  # feet to miles
        elif units == "Miles":
            return distance  # already in miles
        elif units == "Kilometers":
            return distance / 1.60934  # kilometers to miles
        else:
            # Default to meters if unknown unit
            return distance / 1609.34

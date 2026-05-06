#!/usr/bin/env python3
"""VCard Cleaner Script.

This script cleans up VCard files that have been corrupted by iOS syncing,
specifically removing problematic ITEM prefixes that make the VCard non-compliant.

The script processes VCard entries that have:
- PRODID:-//Apple Inc.//iOS
And transforms properties like:
- ITEM1.ADR -> ADR
- ITEM2.EMAIL -> EMAIL
- ITEM1.URL -> URL
- ITEM1.TEL -> TEL
- etc.
"""

import argparse
import base64
import io
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Import PIL only when needed for photo processing
try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None


class VCardCleaner:
    """VCard cleaning utility that processes and normalizes VCard files."""

    def __init__(self):
        """Initialize the VCard cleaner with vCard 4.0 settings (RFC 6350)."""
        # Pattern to match Apple iOS PRODID
        self.ios_prodid_pattern = re.compile(r"PRODID:-//Apple Inc\.//iOS.*//EN")

        # Pattern to match ITEM prefixes (ITEM1., ITEM2., etc.)
        self.item_pattern = re.compile(r"^ITEM\d+\.(.+)", re.MULTILINE)

        # vCard 4.0 properties according to RFC 6350
        self.standard_properties = {
            # Identification Properties
            "FN",
            "N",
            "NICKNAME",
            "PHOTO",
            "BDAY",
            "ANNIVERSARY",
            "GENDER",
            # Delivery Addressing Properties
            "ADR",
            # Communications Properties
            "TEL",
            "EMAIL",
            "IMPP",
            "LANG",
            # Geographical Properties
            "TZ",
            "GEO",
            # Organizational Properties
            "TITLE",
            "ROLE",
            "LOGO",
            "ORG",
            "MEMBER",
            "RELATED",
            # Explanatory Properties
            "CATEGORIES",
            "NOTE",
            "PRODID",
            "REV",
            "SOUND",
            "UID",
            "CLIENTPIDMAP",
            "URL",
            "VERSION",
            # Security Properties
            "KEY",
            # Calendar Properties
            "FBURL",
            "CALADRURI",
            "CALURI",
            # Extended Properties and XML
            "XML",
            # Apple extensions (for ITEM prefix removal)
            "X-ABLABEL",
            "X-ABADR",
            "X-ABCROP-RECTANGLE",
            "X-ABSHOWAS",
            "X-ABUID",
            "X-PHONETIC-FIRST-NAME",
            "X-PHONETIC-LAST-NAME",
            "X-PHONETIC-MIDDLE-NAME",
            "X-SOCIALPROFILE",
        }

        # Apple-specific and non-standard extensions to remove or convert (case-insensitive)
        self.apple_extensions = {
            "X-ABLABEL",
            "X-ABADR",
            "X-ADDRESSING-GRAMMAR",
            "X-ABDATE",
            "X-ABCROP-RECTANGLE",
            "X-ABSHOWAS",
            "X-ABUID",
            "X-PHONETIC-FIRST-NAME",
            "X-PHONETIC-LAST-NAME",
            "X-PHONETIC-MIDDLE-NAME",
            "X-SOCIALPROFILE",
            "X-IMAGEHASH",
            "X-IMAGETYPE",
            "X-SHARED-PHOTO-DISPLAY-PREF",
            "X-UNKNOWN-ELEMENT",
            "X-ABLABEL-ABLABEL",
        }

        # Make a case-insensitive version for lookups
        self.apple_extensions_lower = {ext.lower() for ext in self.apple_extensions}

        # Property mappings for non-standard to standard conversion
        self.property_mappings = {
            "X-ABDATE": "NOTE",  # Convert anniversary dates to notes
            # Could add more mappings here as needed
        }

        # Photo processing settings
        self.max_photo_size = (320, 320)  # Maximum photo dimensions

        # vCard 4.0 uses UTF-8 by default (no CHARSET parameter needed)
        self.default_encoding = "utf-8"

        # vCard 4.0 EMAIL types (lowercase per RFC 6350)
        self.email_type_mappings = {
            "HOME": "home",
            "WORK": "work",
            "PREF": "pref",
            # INTERNET removed - implicit in vCard 4.0
            # X400 removed - obsolete in vCard 4.0
        }

        # Types to remove as redundant in vCard 4.0
        self.redundant_email_types = {"INTERNET", "X400", "OTHER"}

        # vCard 4.0 TEL types (lowercase per RFC 6350)
        self.phone_type_mappings = {
            "HOME": "home",
            "WORK": "work",
            "CELL": "cell",
            "PREF": "pref",
            # vCard 4.0 additional standard types
            "TEXT": "text",
            "VOICE": "voice",
            "FAX": "fax",
            "VIDEO": "video",
            "TEXTPHONE": "cell",    # Map TEXTPHONE to cell for simplicity
            "OTHER": "cell",        # Just assume cell-phone
            # Non-standard mappings to standard types
            "MOBILE": "cell",
            "IPHONE": "cell",
            "PCS": "cell",
            "CAR": "cell",
            "MAIN": "voice",  # Map MAIN to voice as primary
            "MSG": "text",  # Map MSG to text
            "PAGER": "text",  # Map PAGER to text
            "BBS": "text",  # Map BBS to text
            "MODEM": "voice",  # Map MODEM to voice
            "ISDN": "voice",  # Map ISDN to voice
        }

        # Types to remove as redundant in vCard 4.0 (VOICE is implicit)
        self.redundant_phone_types = set()  # Don't remove VOICE in 4.0, it's explicit

        # ADR types - vCard 4.0 (RFC 6350 section 6.3.1)
        self.address_type_mappings = {
            # vCard 4.0 standard types (lowercase)
            "HOME": "home",
            "WORK": "work",
            "PREF": "pref",
            # Legacy types removed in vCard 4.0
            # DOM, INTL, POSTAL, PARCEL are obsolete
        }

        # Types that should be removed (Apple/iOS specific)
        self.forbidden_types = {
            # Remove non-standard Apple types but keep RFC2426 ones
        }

    def normalize_datetime_to_iso8601(self, line):
        """Convert datetime values to ISO 8601 format for vCard 4.0.

        vCard 4.0 requires ISO 8601 format for all date/time values.

        Args:
            line: VCard property line containing date/time

        Returns:
            Line with ISO 8601 formatted date/time
        """
        # Handle REV (revision) timestamps
        if line.upper().startswith("REV:"):
            timestamp_match = re.search(r"REV:(.+)$", line, re.IGNORECASE)
            if timestamp_match:
                timestamp = timestamp_match.group(1).strip()
                
                # Fix iOS bug where a 'T' replaces a '0' in the day (e.g. 2016-03-T8T...)
                timestamp = re.sub(r"-T(\d)T", r"-0\1T", timestamp)
                
                # If it's already in ISO 8601 format, keep it
                if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[Z\+\-]", timestamp):
                    return f"REV:{timestamp}"
                # Try to parse and convert to ISO 8601
                try:
                    # Parse various common formats
                    for fmt in [
                        "%Y-%m-%dT%H:%M:%S+00:00",
                        "%Y-%m-%dT%H:%M:%SZ",
                        "%Y%m%dT%H%M%SZ",
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%dT%H:%M",
                        "%Y-%m-%d",
                    ]:
                        try:
                            clean_timestamp = timestamp.replace("Z", "+00:00").replace("+00:00", "")
                            clean_fmt = fmt.replace("Z", "").replace("+00:00", "")
                            dt = datetime.strptime(clean_timestamp, clean_fmt)
                            # Convert to UTC ISO 8601
                            iso_timestamp = dt.replace(tzinfo=timezone.utc).strftime("%Y%m%dT%H%M%S%z")
                            return f"REV:{iso_timestamp}"
                        except ValueError:
                            continue
                except Exception:
                    pass
                
                # Fallback: if we still couldn't parse it but it looks somewhat like a date
                if "T" in timestamp:
                    return f"REV:{timestamp}Z"

        # Handle BDAY (birthday) dates
        if line.upper().startswith("BDAY:"):
            date_match = re.search(r"BDAY:(.+)$", line, re.IGNORECASE)
            if date_match:
                date_str = date_match.group(1).strip()
                # If already in ISO format (YYYY-MM-DD), keep it
                if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                    return line
                # Try to parse various date formats
                try:
                    for fmt in ["%Y%m%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d"]:
                        try:
                            dt = datetime.strptime(date_str, fmt)
                            return f"BDAY:{dt.strftime('%Y-%m-%d')}"
                        except ValueError:
                            continue
                except Exception:
                    pass

        # Handle ANNIVERSARY dates (new in vCard 4.0)
        if line.upper().startswith("ANNIVERSARY:"):
            date_match = re.search(r"ANNIVERSARY:(.+)$", line, re.IGNORECASE)
            if date_match:
                date_str = date_match.group(1).strip()
                # If already in ISO format, keep it
                if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                    return line
                # Try to parse and convert
                try:
                    for fmt in ["%Y%m%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d"]:
                        try:
                            dt = datetime.strptime(date_str, fmt)
                            return f"ANNIVERSARY:{dt.strftime('%Y-%m-%d')}"
                        except ValueError:
                            continue
                except Exception:
                    pass

        return line

    def ensure_utf8_encoding(self, vcard_text):
        """Ensure proper UTF-8 encoding and remove CHARSET parameters.

        vCard 4.0 uses UTF-8 by default and doesn't use CHARSET parameters.

        Args:
            vcard_text: VCard entry text

        Returns:
            VCard text with UTF-8 compliance
        """
        lines = vcard_text.split("\n")
        processed_lines = []

        for line in lines:
            # Remove CHARSET parameters (not used in vCard 4.0)
            line = re.sub(r";CHARSET=[^;:]*", "", line, flags=re.IGNORECASE)

            # Ensure the line is properly UTF-8 encoded
            if isinstance(line, str):
                # String is already Unicode in Python 3, just clean up any encoding artifacts
                line = line.encode("utf-8", errors="replace").decode("utf-8")

            processed_lines.append(line)

        return "\n".join(processed_lines)

    def is_ios_entry(self, vcard_text):
        """Check if a VCard entry was created by iOS."""
        return bool(self.ios_prodid_pattern.search(vcard_text))

    def normalize_type_parameter(self, type_value, type_mappings, redundant_types=None, property_name=None):
        """Normalize a TYPE parameter value using the provided mappings and remove redundant types.

        Args:
            type_value: The original type value (e.g., "INTERNET,HOME", "CELL,VOICE")
            type_mappings: Dictionary mapping old values to new values
            redundant_types: Set of types to remove as redundant
            property_name: The property name (for special logic)

        Returns:
            Normalized type value with redundant types removed
        """
        if not type_value:
            return type_value

        if redundant_types is None:
            redundant_types = set()

        # Handle comma-separated multiple types
        types = [t.strip() for t in type_value.split(",")]
        normalized_types = []
        has_cell = False

        # First pass: identify what types we have
        for type_item in types:
            if type_item.upper() == "CELL":
                has_cell = True

        for type_item in types:
            # Skip redundant types
            if type_item.upper() in {t.upper() for t in redundant_types}:
                continue

            # Handle 'pref' specially - it's not a type but a preference parameter in vCard 4.0
            if type_item.lower() == "pref":
                continue

            # Special handling for MAIN on phone numbers
            if property_name == "TEL" and type_item.upper() == "MAIN":
                # If we already have CELL, map MAIN to HOME to avoid duplicate
                # If no CELL, map MAIN to CELL
                if has_cell:
                    normalized = "HOME"
                else:
                    normalized = "CELL"
            else:
                # Normal mapping
                normalized = type_mappings.get(type_item.upper(), type_item.lower())

            if normalized not in normalized_types:  # Avoid duplicates
                normalized_types.append(normalized)

        return ",".join(normalized_types)

    def remove_item_prefixes(self, line):
        """Remove ITEM prefixes from VCard properties (ITEM1.EMAIL, ITEM2.ADR, etc.).

        Args:
            line: A VCard property line

        Returns:
            Line without ITEM prefixes
        """
        # Remove ITEM prefix pattern (case insensitive)
        item_pattern = re.compile(r"^item\d+\.", re.IGNORECASE)
        return item_pattern.sub("", line)

    def normalize_property_types(self, line):
        """Normalize TYPE parameters in EMAIL, TEL, and ADR properties.

        Removes redundant types like INTERNET for emails and VOICE for phones.

        Args:
            line: A VCard property line

        Returns:
            Line with normalized TYPE parameters
        """
        # Check if this line contains a TYPE parameter (case insensitive)
        if ";type=" not in line.lower():
            return line

        # Determine property type and get appropriate mappings
        property_name = line.split(";")[0].split(":")[0].upper()

        if property_name == "EMAIL":
            type_mappings = self.email_type_mappings
            redundant_types = self.redundant_email_types
        elif property_name == "TEL":
            type_mappings = self.phone_type_mappings
            redundant_types = self.redundant_phone_types
        elif property_name == "ADR":
            type_mappings = self.address_type_mappings
            redundant_types = set()  # Keep all ADR types
        else:
            # For other properties, just return as-is
            return line

        # Use regex to find and replace TYPE parameter
        def replace_type(match):
            type_value = match.group(1)
            normalized_type = self.normalize_type_parameter(
                type_value,
                type_mappings,
                redundant_types,
                property_name=property_name,
            )

            result = ""
            if normalized_type:
                result += f";TYPE={normalized_type}"
            return result

        if ":" in line:
            prop_part, val_part = line.split(":", 1)
        else:
            prop_part, val_part = line, ""

        # Pattern to match ;type=value (handling various cases)
        type_pattern = re.compile(r";type=([^;:]+)", re.IGNORECASE)
        prop_part = type_pattern.sub(replace_type, prop_part)

        # Clean up any double semicolons that might result from removing TYPE parameters
        prop_part = re.sub(r";;+", ";", prop_part)

        # Clean up semicolon before colon (if TYPE was at the end)
        prop_part = re.sub(r";$", "", prop_part)

        if ":" in line:
            return f"{prop_part}:{val_part}"
        return prop_part

    def remove_redundant_value_parameters(self, line):
        """Remove redundant VALUE parameters from VCard properties.

        - VALUE=UNKNOWN (doesn't make sense)
        - VALUE=URI (redundant for URL properties)
        - VALUE=date (redundant for BDAY)
        - VALUE=BINARY (redundant for PHOTO with ENCODING)

        Keep VALUE=DATE-AND-OR-TIME for REV properties and VALUE=TEXT for PRODID.

        Args:
            line: A VCard property line

        Returns:
            Line with redundant VALUE parameters removed
        """
        # Don't process REV properties with VALUE=DATE-AND-OR-TIME
        if line.upper().startswith("REV;") and "VALUE=DATE-AND-OR-TIME" in line.upper():
            return line

        # Don't process PRODID properties with VALUE=TEXT
        if line.upper().startswith("PRODID;") and "VALUE=TEXT" in line.upper():
            return line

        if ":" not in line:
            return line
            
        parts = line.split(":", 1)
        prop_part = parts[0]
        val_part = parts[1]

        # List of redundant VALUE parameters to remove
        redundant_values = {
            "VALUE=UNKNOWN",
            "VALUE=URI",
            "VALUE=TEXT",  # Remove from non-PRODID properties
            "VALUE=date",
            "VALUE=BINARY",
        }

        # Remove redundant VALUE parameters (case insensitive)
        for redundant_value in redundant_values:
            # Match the VALUE parameter with optional comma or semicolon
            patterns = [
                f";{redundant_value};",  # ;VALUE=XXX;
                f";{redundant_value}$",  # ;VALUE=XXX (at end)
                f",{redundant_value};",  # ,VALUE=XXX;
                f",{redundant_value}$",  # ,VALUE=XXX (at end)
            ]

            for pattern in patterns:
                # Replace with appropriate separator
                if pattern.endswith(";"):
                    prop_part = re.sub(re.escape(pattern), ";", prop_part, flags=re.IGNORECASE)
                else:  # ends with '$'
                    pattern_str = pattern[:-1]
                    prop_part = re.sub(re.escape(pattern_str) + r"$", "", prop_part, flags=re.IGNORECASE)

        # Clean up any double separators that might result
        prop_part = re.sub(r";;+", ";", prop_part)

        return f"{prop_part}:{val_part}"

    def clean_address_field(self, line):
        r"""Clean up address fields by removing literal \n sequences and normalizing formatting.

        Address fields (ADR) often contain:
        - Literal \n sequences that should be spaces
        - Literal \, sequences that should be commas
        - Extra spaces that should be normalized

        Args:
            line: A VCard property line

        Returns:
            Line with cleaned address formatting
        """
        # Only process ADR (address) properties
        if not line.upper().startswith("ADR"):
            return line

        # Replace literal \n with spaces
        cleaned_line = line.replace("\\n", " ")

        # Replace linebreak with spaces
        cleaned_line = cleaned_line.replace("\n", " ")

        # Replace literal \, with regular commas
        cleaned_line = cleaned_line.replace("\\,", ",")

        # Normalize multiple spaces to single spaces
        cleaned_line = re.sub(r"\s+", " ", cleaned_line)

        # Clean up spaces around semicolons (VCard field separators)
        cleaned_line = re.sub(r"\s*;\s*", ";", cleaned_line)

        # Clean up trailing spaces before semicolons
        cleaned_line = re.sub(r"\s+;", ";", cleaned_line)

        # Additional normalization: ensure ADR has 7 semicolon-separated components
        # (PO Box;Extended;Street;Locality;Region;Postal;Country)
        try:
            if ":" not in line:
                return cleaned_line
            prefix, value = cleaned_line.split(":", 1)

            parts = value.split(";")

            # If already 7 components and extended is empty, accept as-is
            if len(parts) == 7 and parts[1] == "":
                return cleaned_line

            # Build from non-empty tokens: easier heuristics
            non_empty = [p.strip() for p in parts if p.strip() != ""]

            street = ""
            locality = ""
            region = ""
            postal = ""
            country = ""

            if len(non_empty) >= 4:
                country = non_empty[-1]
                postal = non_empty[-2]
                locality = non_empty[-3]
                street = " ".join(non_empty[:-3])
            elif len(non_empty) == 3:
                street = non_empty[0]
                locality = non_empty[1]
                country = non_empty[2]
            elif len(non_empty) == 2:
                street = non_empty[0]
                country = non_empty[1]
            elif len(non_empty) == 1:
                street = non_empty[0]

            # Preserve PO box if it was explicitly provided as the very first component
            po_box = ""
            if parts and parts[0].strip() != "":
                po_box = parts[0].strip()

            # Heuristic: if street ends with a country name, pull it out
            known_countries = {
                "germany",
                "deutschland",
                "brazil",
                "brasil",
                "united states",
                "usa",
                "uk",
                "austria",
                "switzerland",
                "france",
                "spain",
                "italy",
            }
            if street:
                s_lower = street.lower()
                for cname in known_countries:
                    if s_lower.endswith(" " + cname):
                        # remove trailing country
                        country = street[-(len(cname) + 1) :].strip()
                        street = street[: -(len(cname) + 1)].strip()
                        break

                # If street now ends with a likely locality (single capitalized token), split it off
                parts_st = street.split()
                if len(parts_st) >= 2:
                    last_tok = parts_st[-1]
                    if last_tok[0].isalpha() and last_tok[0].isupper() and not any(ch.isdigit() for ch in last_tok):
                        locality = last_tok
                        street = " ".join(parts_st[:-1])

            new = [""] * 7
            new[0] = po_box
            new[1] = ""  # force Extended empty per user note
            new[2] = street
            new[3] = locality
            new[4] = region
            new[5] = postal
            new[6] = country

            fixed_value = ";".join(new)
            return f"{prefix}:{fixed_value}"
        except Exception:
            return cleaned_line

    def remove_duplicate_photos(self, vcard_text):
        """Remove duplicate PHOTO properties, keeping only the first one.

        Some VCards have multiple PHOTO properties which can cause issues
        and significantly increase file size. This method keeps only the
        first PHOTO property and removes all others.

        Args:
            vcard_text: The complete VCard entry text

        Returns:
            VCard text with only the first PHOTO property
        """
        lines = vcard_text.split("\n")
        cleaned_lines = []
        found_photo = False

        i = 0
        while i < len(lines):
            line = lines[i]

            # Check if this line starts a PHOTO property
            if line.startswith("PHOTO;") or line.startswith("PHOTO:"):
                if not found_photo:
                    # This is the first PHOTO, keep it
                    found_photo = True
                    cleaned_lines.append(line)

                    # Handle multi-line PHOTO data (continuation lines start with space)
                    j = i + 1
                    while j < len(lines) and lines[j].startswith(" "):
                        cleaned_lines.append(lines[j])
                        j += 1
                    i = j - 1  # -1 because the loop will increment
                else:
                    # This is a duplicate PHOTO, skip it
                    # Skip this PHOTO and its continuation lines
                    j = i + 1
                    while j < len(lines) and lines[j].startswith(" "):
                        j += 1
                    i = j - 1  # -1 because the loop will increment
            else:
                # Not a PHOTO line, add it normally
                cleaned_lines.append(line)

            i += 1

        return "\n".join(cleaned_lines)

    def generate_new_uid(self):
        """Generate a new UID in the same format as the original VCards (10-character hex).

        Returns:
            A new UID string
        """
        # Generate a UUID4 and take the first 10 characters of the hex representation
        new_uuid = uuid.uuid4().hex[:10]
        return new_uuid

    def update_uid_and_prodid(self, vcard_text):
        """Update UID and PRODID properties to distinguish cleaned contacts from originals.

        - Generates a new UID for each contact
        - Sets PRODID to indicate this was processed by VCard Cleaner

        Args:
            vcard_text: The VCard entry text

        Returns:
            VCard text with updated UID and PRODID
        """
        lines = vcard_text.split("\n")
        processed_lines = []

        has_uid = False
        has_prodid = False
        new_uid = self.generate_new_uid()

        for line in lines:
            if not line.strip():
                processed_lines.append(line)
                continue

            property_name = line.split(";")[0].split(":")[0].upper()

            if property_name == "UID":
                # Preserve existing UID but format as URN
                if ":" in line:
                    prop_part, val_part = line.split(":", 1)
                    if not val_part.lower().startswith("urn:uuid:"):
                        processed_lines.append(f"{prop_part}:urn:uuid:{val_part}")
                    else:
                        processed_lines.append(line)
                else:
                    processed_lines.append(f"UID:urn:uuid:{new_uid}")
                has_uid = True
            elif property_name == "PRODID":
                # Replace existing PRODID with our custom one
                processed_lines.append("PRODID:-//VCard Cleaner v2.0//RFC 6350//EN")
                has_prodid = True
            else:
                processed_lines.append(line)

        # Add UID and PRODID if they don't exist
        # Insert after VERSION but before other properties
        if not has_uid or not has_prodid:
            # Find position after VERSION
            for i, line in enumerate(processed_lines):
                if line.upper().startswith("VERSION:"):
                    insert_pos = i + 1
                    if not has_prodid:
                        processed_lines.insert(insert_pos, "PRODID:-//VCard Cleaner v2.0//RFC 6350//EN")
                        insert_pos += 1
                    if not has_uid:
                        processed_lines.insert(insert_pos, f"UID:urn:uuid:{new_uid}")
                    break

        return "\n".join(processed_lines)

    def process_apple_extensions(self, line):
        """Process Apple-specific extensions for RFC2426 compliance.

        - Remove non-standard X-ABLABEL, X-ABADR, etc.
        - Convert some extensions to standard properties where possible
        - Remove properties that have no RFC2426 equivalent

        Args:
            line: A VCard property line

        Returns:
            Processed line, empty string if line should be removed, or mapped property
        """
        # Get property name
        property_name = line.split(";")[0].split(":")[0].upper()

        # Remove Apple-specific extensions that have no standard equivalent (case-insensitive)
        if property_name.upper() in self.apple_extensions or property_name.lower() in self.apple_extensions_lower:
            # Special handling for some extensions
            if property_name == "X-ABDATE":
                # Convert anniversary dates to NOTE
                value_part = line.split(":", 1)
                if len(value_part) > 1:
                    # Extract date and create note
                    date_value = value_part[1]
                    return f"NOTE:Anniversary: {date_value}"

            # For most Apple extensions, just remove them
            return ""

        # Handle PRODID to ensure it's RFC2426 compliant
        if property_name == "PRODID" and "Apple Inc." in line:
            # Replace Apple PRODID with a generic one
            return "PRODID:-//VCard Cleaner v2.0//RFC 6350//EN"

        # Remove google.com/profiles/ URLs
        if property_name == "URL" and "google.com/profiles/" in line:
            return ""

        return line

    def ensure_rfc6350_compliance(self, vcard_text):
        """Ensure the VCard is fully RFC 6350 (vCard 4.0) compliant.

        - Ensuring VERSION is 4.0
        - Ensuring required properties (VERSION, FN) are present
        - Adding UID if not present (recommended in vCard 4.0)
        - Removing non-compliant properties
        - Ensuring UTF-8 encoding

        Args:
            vcard_text: The VCard entry text

        Returns:
            RFC 6350 (vCard 4.0) compliant VCard text
        """
        lines = vcard_text.split("\n")
        processed_lines = []

        has_version = False
        has_fn = False
        has_n = False
        skip_continuations = False

        for line in lines:
            if line.startswith(" ") or line.startswith("\t"):
                if skip_continuations:
                    continue
                else:
                    processed_lines.append(line)
                    continue
            else:
                skip_continuations = False

            if not line.strip():
                processed_lines.append(line)
                continue

            property_name = line.split(";")[0].split(":")[0].upper()

            # Track required properties
            if property_name == "VERSION":
                has_version = True
                # Ensure VERSION is 4.0
                processed_lines.append("VERSION:4.0")
                continue
            elif property_name == "FN":
                has_fn = True
            elif property_name == "N":
                has_n = True

            # Process Apple extensions
            processed_line = self.process_apple_extensions(line)
            
            # Remove tel: prefix from TEL property values
            if processed_line and property_name == "TEL":
                if ":" in processed_line:
                    prop_part, val_part = processed_line.split(":", 1)
                    if val_part.lower().startswith("tel:"):
                        val_part = val_part[4:]
                    processed_line = f"{prop_part}:{val_part}"
                        
            if not processed_line:
                skip_continuations = True
            else:
                processed_lines.append(processed_line)

        # Ensure required properties are present
        if not has_version:
            # Insert VERSION after BEGIN:VCARD
            for i, line in enumerate(processed_lines):
                if line.upper().startswith("BEGIN:VCARD"):
                    processed_lines.insert(i + 1, "VERSION:4.0")
                    break

        # vCard 4.0 requires FN, N is recommended but not required
        if not has_fn:
            if has_n:
                # Try to generate FN from N
                for line in processed_lines:
                    if line.upper().startswith("N:"):
                        n_parts = line.split(":", 1)[1].split(";")
                        if len(n_parts) >= 2 and (n_parts[0] or n_parts[1]):
                            # Create FN from available name parts
                            name_parts = []
                            if n_parts[1]:  # Given name
                                name_parts.append(n_parts[1])
                            if n_parts[0]:  # Family name
                                name_parts.append(n_parts[0])
                            fn_value = " ".join(name_parts)
                            processed_lines.insert(-1, f"FN:{fn_value}")  # Insert before END:VCARD
                            break
            else:
                # No N property, create a minimal FN
                processed_lines.insert(-1, "FN:Contact")  # Insert before END:VCARD

        # Find current FN value for honorifics and N-derivation
        fn_val = None
        for line in processed_lines:
            if line.upper().startswith("FN:"):
                fn_val = line.split(":", 1)[1]
                break

        # Derive N from FN if missing
        if not has_n and fn_val:
            name_parts = fn_val.strip().split()
            if len(name_parts) >= 2:
                # Heuristic: Last word is family name, others are given name
                family = name_parts[-1]
                given = " ".join(name_parts[:-1])
                n_val = f"{family};{given};;;"
            else:
                # Single name: treat as given name
                n_val = f";{fn_val.strip()};;;"

            # Find insertion point: before END:VCARD
            insert_idx = len(processed_lines)
            for idx, pl in enumerate(processed_lines):
                if pl.upper().strip() == "END:VCARD":
                    insert_idx = idx
                    break
            processed_lines.insert(insert_idx, f"N:{n_val}")

        # Ensure N property has correct number of semicolons and extract honorifics from FN

        for i, line in enumerate(processed_lines):
            if line.upper().startswith("N:"):
                n_prefix, n_val = line.split(":", 1)
                n_parts = n_val.split(";")
                
                # Ensure exactly 5 components (4 semicolons) for vCard 4.0 compliance
                while len(n_parts) < 5:
                    n_parts.append("")
                
                # If FN has an honorific prefix but N doesn't, copy it over
                if fn_val and not n_parts[3].strip():
                    prefixes = ["Dr.", "Prof.", "Mr.", "Mrs.", "Ms.", "Rev.", "Dr", "Prof", "Mr", "Mrs", "Ms", "Rev", "Sir", "Madam"]
                    for p in prefixes:
                        if fn_val.startswith(p + " ") or fn_val == p:
                            n_parts[3] = p
                            break
                            
                # If there are extra parts, merge them into the last part (suffix) to strictly adhere to 5 parts
                if len(n_parts) > 5:
                    n_parts[4] = ";".join(n_parts[4:])
                    n_parts = n_parts[:5]
                    
                processed_lines[i] = f"{n_prefix}:{';'.join(n_parts)}"

        return "\n".join(processed_lines)

    def fix_preference_conflicts(self, vcard_text):
        """Remove 'pref' and 'PREF=...' parameters from all properties entirely.
        
        Args:
            vcard_text: The VCard entry text

        Returns:
            VCard text with preferences removed
        """
        lines = vcard_text.split("\n")
        processed_lines = []

        for line in lines:
            if not line.strip():
                processed_lines.append(line)
                continue

            # Check if this line has a preference
            if "pref" in line.lower():
                if ":" in line:
                    prop_part, val_part = line.split(":", 1)
                else:
                    prop_part, val_part = line, ""
                    
                # Remove any 'pref' or 'PREF=x' from this line
                prop_part = re.sub(r";PREF=\d+|PREF=\d+;|,pref|pref,|;pref|pref", "", prop_part, flags=re.IGNORECASE)
                # Clean up any double commas or semicolons
                prop_part = re.sub(r",,+", ",", prop_part)
                prop_part = re.sub(r";;+", ";", prop_part)
                prop_part = re.sub(r";,|,;", ";", prop_part)
                # Clean up TYPE= with no value
                prop_part = re.sub(r"TYPE=,", "TYPE=", prop_part)
                prop_part = re.sub(r"TYPE=;", "", prop_part)
                prop_part = re.sub(r"TYPE=$", "", prop_part)
                
                # Clean up trailing semicolons
                prop_part = re.sub(r"[,;]+$", "", prop_part)
                
                if ":" in line:
                    line = f"{prop_part}:{val_part}"
                else:
                    line = prop_part
                    
            processed_lines.append(line)

        return "\n".join(processed_lines)

    def process_photo_data(self, photo_data, encoding="b"):
        """Process and downscale photo data if needed.

        Args:
            photo_data: The base64 encoded photo data
            encoding: The encoding type ('b' for base64, 'BASE64', etc.)

        Returns:
            Processed photo data (base64 encoded) or original if processing fails
        """
        if not PIL_AVAILABLE:
            return photo_data

        # Quick heuristic: if photo data is small, probably doesn't need processing
        # This avoids reformatting small photos unnecessarily
        photo_data_clean = "".join(photo_data.split())
        if len(photo_data_clean) < 100000:  # Less than ~75KB base64 data
            return photo_data

        try:
            # Decode base64 data
            if encoding.upper() in ["B", "BASE64"]:
                # Remove any whitespace and newlines for decoding
                clean_data = "".join(photo_data.split())
                image_bytes = base64.b64decode(clean_data)
            else:
                # If not base64, return original
                return photo_data

            # Open image with PIL
            if not PIL_AVAILABLE or Image is None:
                return photo_data

            image = Image.open(io.BytesIO(image_bytes))

            # Check if image needs resizing
            width, height = image.size
            if width <= self.max_photo_size[0] and height <= self.max_photo_size[1]:
                # Image is already small enough, return original data COMPLETELY UNCHANGED
                return photo_data

            # Convert to RGB if necessary (for PNG output)
            if image.mode in ("RGBA", "LA", "P"):
                # Keep transparency for RGBA, convert others to RGB
                if image.mode != "RGBA":
                    image = image.convert("RGB")
            elif image.mode != "RGB":
                image = image.convert("RGB")

            # Calculate new size maintaining aspect ratio
            image.thumbnail(self.max_photo_size, Image.Resampling.LANCZOS)

            # Save as JPEG with high compression to reduce file size
            output_buffer = io.BytesIO()
            if image.mode == "RGBA":
                # Convert RGBA to RGB for JPEG
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[-1])
                background.save(output_buffer, format="JPEG", quality=85, optimize=True)
            else:
                image.save(output_buffer, format="JPEG", quality=85, optimize=True)

            # Encode back to base64
            output_buffer.seek(0)
            new_image_data = base64.b64encode(output_buffer.read()).decode("ascii")

            # Format the base64 data with line breaks to match original VCard format
            # First line goes directly after the colon, subsequent lines start with space
            chunks = [new_image_data[i : i + 74] for i in range(0, len(new_image_data), 74)]
            if len(chunks) == 1:
                formatted_data = chunks[0]
            else:
                formatted_data = chunks[0] + "\n " + "\n ".join(chunks[1:])

            print(f"  Photo resized from {width}x{height} to {image.size[0]}x{image.size[1]}")
            return formatted_data

        except Exception as e:
            print(f"  Warning: Could not process photo data: {e}")
            return photo_data

    def process_photo_line(self, line):
        """Process a PHOTO line and convert to vCard 4.0 data URI format.

        Args:
            line: The PHOTO line from VCard

        Returns:
            Processed PHOTO line in vCard 4.0 data URI format
        """
        # Match PHOTO property with encoding and type (vCard 3.0 format)
        photo_match = re.match(r"^(PHOTO;.*?ENCODING=([^;:]+).*?TYPE=([^;:]+).*?):(.*)", line, re.DOTALL)
        if not photo_match:
            # Try simpler pattern or already vCard 4.0 data URI format
            photo_match = re.match(r"^(PHOTO):(.*)", line, re.DOTALL)
            if not photo_match:
                return line
            # If it's already in data URI format, just process the data
            if line.startswith("PHOTO:data:"):
                return line.replace("\\,", ",")
            property_part, photo_data = photo_match.groups()
            encoding = "base64"  # Default for vCard 4.0
            image_type = "JPEG"  # Default
        else:
            property_part, encoding, image_type, photo_data = photo_match.groups()

        # Process the photo data
        photo_data = photo_data.replace("\\,", ",")
        processed_data = self.process_photo_data(photo_data, encoding)

        # Convert to vCard 4.0 data URI format (no ENCODING parameter)
        if processed_data != photo_data or "ENCODING=" in line:
            # Use JPEG format for processed images
            mime_type = "image/jpeg"
        else:
            # Try to preserve original image type
            if image_type.upper() == "PNG":
                mime_type = "image/png"
            elif image_type.upper() in ["JPG", "JPEG"]:
                mime_type = "image/jpeg"
            else:
                mime_type = "image/jpeg"  # Default

        # Return in vCard 4.0 data URI format
        return f"PHOTO:data:{mime_type};base64,{processed_data}"

    def clean_vcard_entry(
        self,
        vcard_text,
        process_photos=True,
        normalize_types=True,
        fix_preferences=True,
        ensure_rfc6350=True,
    ):
        """Clean a single VCard entry to vCard 4.0 (RFC 6350) compliance."""
        # Ensure UTF-8 encoding first (vCard 4.0 requirement)
        vcard_text = self.ensure_utf8_encoding(vcard_text)

        # Remove duplicate photos first (applies to all VCards, not just iOS ones)
        vcard_text = self.remove_duplicate_photos(vcard_text)

        if not self.is_ios_entry(vcard_text):
            # Even for non-iOS entries, we might want to process photos and normalize types
            if process_photos or normalize_types or fix_preferences or ensure_rfc6350:
                return self.process_all_in_entry(
                    vcard_text,
                    process_photos,
                    normalize_types,
                    fix_preferences,
                    ensure_rfc6350,
                )
            return vcard_text

        # Split into lines for processing
        lines = vcard_text.split("\n")
        cleaned_lines = []

        i = 0
        while i < len(lines):
            line = lines[i]

            # Remove ITEM prefixes from all lines
            processed_line = self.remove_item_prefixes(line)

            # Handle multiline address fields specially
            if processed_line.upper().startswith("ADR"):
                # Collect all continuation lines for the address
                address_lines = [processed_line]
                j = i + 1
                while j < len(lines) and lines[j].startswith(" "):
                    address_lines.append(self.remove_item_prefixes(lines[j]))
                    j += 1

                # Process the complete address
                complete_address = "\n".join(address_lines)

                # Normalize types for ADR properties
                if normalize_types:
                    complete_address = self.normalize_property_types(complete_address)

                # Remove redundant VALUE parameters
                complete_address = self.remove_redundant_value_parameters(complete_address)

                # Clean up address fields (remove \n and \, sequences)
                complete_address = self.clean_address_field(complete_address)

                # Process Apple extensions for RFC2426 compliance
                if ensure_rfc6350:
                    complete_address = self.process_apple_extensions(complete_address)
                    if not complete_address:
                        i = j
                        continue

                # Add the processed address lines
                cleaned_lines.extend(complete_address.split("\n"))

                # Skip the lines we already processed
                i = j
                continue

            # Normalize types for EMAIL, TEL properties (non-ADR)
            if normalize_types:
                processed_line = self.normalize_property_types(processed_line)

            # Remove redundant VALUE parameters
            processed_line = self.remove_redundant_value_parameters(processed_line)

            # Normalize datetime values to ISO 8601 (vCard 4.0 requirement)
            processed_line = self.normalize_datetime_to_iso8601(processed_line)

            # Process Apple extensions for vCard 4.0 compliance
            if ensure_rfc6350:
                processed_line = self.process_apple_extensions(processed_line)
                # Skip empty lines (removed Apple extensions)
                if not processed_line:
                    i += 1
                    while i < len(lines) and (lines[i].startswith(" ") or lines[i].startswith("\t")):
                        i += 1
                    continue

            # Process photos if enabled and this is a PHOTO line
            if process_photos and processed_line.startswith("PHOTO;"):
                # Handle multi-line PHOTO data
                photo_lines = [processed_line]
                j = i + 1
                # Collect continuation lines (lines starting with space)
                while j < len(lines) and lines[j].startswith(" "):
                    photo_lines.append(lines[j])
                    j += 1

                # Process the complete PHOTO entry
                complete_photo = "\n".join(photo_lines)
                processed_photo = self.process_photo_line(complete_photo)

                # Add the processed photo lines
                cleaned_lines.extend(processed_photo.split("\n"))

                # Skip the lines we already processed
                i = j
            else:
                cleaned_lines.append(processed_line)
                i += 1

        # Fix preference conflicts and ensure RFC2426 compliance after all other processing
        result = "\n".join(cleaned_lines)
        if fix_preferences:
            result = self.fix_preference_conflicts(result)
        if ensure_rfc6350:
            result = self.ensure_rfc6350_compliance(result)

        # Update UID and PRODID to distinguish cleaned contacts
        result = self.update_uid_and_prodid(result)

        return result

    def process_all_in_entry(
        self,
        vcard_text,
        process_photos=True,
        normalize_types=True,
        fix_preferences=True,
        ensure_rfc6350=True,
    ):
        """Process photos, normalize types, fix preferences, and ensure RFC2426 compliance in any VCard entry."""
        # Remove duplicate photos first
        vcard_text = self.remove_duplicate_photos(vcard_text)

        lines = vcard_text.split("\n")
        cleaned_lines = []

        i = 0
        while i < len(lines):
            line = lines[i]

            # Remove ITEM prefixes from all lines (not just iOS entries)
            line = self.remove_item_prefixes(line)

            # Handle multiline address fields specially
            if line.upper().startswith("ADR"):
                # Collect all continuation lines for the address
                address_lines = [line]
                j = i + 1
                while j < len(lines) and lines[j].startswith(" "):
                    address_lines.append(lines[j])
                    j += 1

                # Process the complete address
                complete_address = "\n".join(address_lines)

                # Normalize types for ADR properties
                if normalize_types:
                    complete_address = self.normalize_property_types(complete_address)

                # Remove redundant VALUE parameters
                complete_address = self.remove_redundant_value_parameters(complete_address)

                # Clean up address fields (remove \n and \, sequences)
                complete_address = self.clean_address_field(complete_address)

                # Add the processed address lines
                cleaned_lines.extend(complete_address.split("\n"))

                # Skip the lines we already processed
                i = j
                continue

            # Normalize types for EMAIL, TEL properties (non-ADR)
            if normalize_types:
                line = self.normalize_property_types(line)

            # Remove redundant VALUE parameters
            line = self.remove_redundant_value_parameters(line)

            # Normalize datetime values to ISO 8601 (vCard 4.0 requirement)
            line = self.normalize_datetime_to_iso8601(line)

            # Process Apple extensions for vCard 4.0 compliance
            if ensure_rfc6350:
                line = self.process_apple_extensions(line)
                # Skip empty lines (removed Apple extensions)
                if not line:
                    i += 1
                    while i < len(lines) and (lines[i].startswith(" ") or lines[i].startswith("\t")):
                        i += 1
                    continue

            # Process photos if this is a PHOTO line
            if process_photos and line.startswith("PHOTO;"):
                # Handle multi-line PHOTO data
                photo_lines = [line]
                j = i + 1
                # Collect continuation lines (lines starting with space)
                while j < len(lines) and lines[j].startswith(" "):
                    photo_lines.append(lines[j])
                    j += 1

                # Process the complete PHOTO entry
                complete_photo = "\n".join(photo_lines)
                processed_photo = self.process_photo_line(complete_photo)

                # Add the processed photo lines
                cleaned_lines.extend(processed_photo.split("\n"))

                # Skip the lines we already processed
                i = j
            else:
                cleaned_lines.append(line)
                i += 1

        # Fix preference conflicts and ensure RFC2426 compliance after all other processing
        result = "\n".join(cleaned_lines)
        if fix_preferences:
            result = self.fix_preference_conflicts(result)
        if ensure_rfc6350:
            result = self.ensure_rfc6350_compliance(result)

        # Update UID and PRODID to distinguish cleaned contacts
        result = self.update_uid_and_prodid(result)

        return result

    def process_photos_in_entry(self, vcard_text):
        """Process photos in any VCard entry (not just iOS entries)."""
        lines = vcard_text.split("\n")
        cleaned_lines = []

        i = 0
        while i < len(lines):
            line = lines[i]

            # Process photos if this is a PHOTO line
            if line.startswith("PHOTO;"):
                # Handle multi-line PHOTO data
                photo_lines = [line]
                j = i + 1
                # Collect continuation lines (lines starting with space)
                while j < len(lines) and lines[j].startswith(" "):
                    photo_lines.append(lines[j])
                    j += 1

                # Process the complete PHOTO entry
                complete_photo = "\n".join(photo_lines)
                processed_photo = self.process_photo_line(complete_photo)

                # Add the processed photo lines
                cleaned_lines.extend(processed_photo.split("\n"))

                # Skip the lines we already processed
                i = j
            else:
                cleaned_lines.append(line)
                i += 1

        return "\n".join(cleaned_lines)

    def split_vcards(self, content):
        """Split VCard file content into individual VCard entries."""
        # Split on BEGIN:VCARD but keep the delimiter
        parts = re.split(r"(BEGIN:VCARD)", content)

        vcards = []
        for i in range(1, len(parts), 2):  # Start from 1, step by 2
            if i + 1 < len(parts):
                vcard = parts[i] + parts[i + 1]
                # Ensure each VCard ends with a newline if it doesn't already
                if not vcard.endswith("\n"):
                    vcard += "\n"
                vcards.append(vcard)

        return vcards

    def clean_vcard_file(
        self,
        input_file,
        output_file=None,
        process_photos=True,
        normalize_types=True,
        fix_preferences=True,
    ):
        """Clean an entire VCard file."""
        input_path = Path(input_file)

        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")

        print(f"Reading VCard file: {input_path}")

        # Read the input file
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        print(f"File size: {len(content):,} characters")

        # Split into individual VCards
        vcards = self.split_vcards(content)
        print(f"Found {len(vcards)} VCard entries")

        # Clean each VCard entry
        cleaned_vcards = []
        ios_entries_count = 0
        cleaned_count = 0

        for i, vcard in enumerate(vcards):
            if i % 100 == 0 and i > 0:
                print(f"Processed {i}/{len(vcards)} entries...")

            original_vcard = vcard

            if self.is_ios_entry(vcard):
                ios_entries_count += 1
                print(f"Processing iOS entry {ios_entries_count}...")

            # Clean the VCard (includes photo processing, type normalization,
            # preference fixing, and RFC2426 compliance if enabled)
            cleaned_vcard = self.clean_vcard_entry(
                vcard,
                process_photos,
                normalize_types,
                fix_preferences,
                ensure_rfc6350=True,
            )

            # Check if anything was actually changed
            if original_vcard != cleaned_vcard:
                cleaned_count += 1

            cleaned_vcard += "\n"

            cleaned_vcards.append(cleaned_vcard)

        # Join all VCards back together with proper line breaks
        # Each VCard should already end with a newline from split_vcards
        cleaned_content = "".join(cleaned_vcards)

        # Determine output file name
        if output_file is None:
            suffix = "_cleaned_with_photos" if process_photos else "_cleaned"
            output_file = input_path.parent / f"{input_path.stem}{suffix}{input_path.suffix}"
        else:
            output_file = Path(output_file)

        print(f"Writing cleaned file: {output_file}")

        # Write the cleaned content
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(cleaned_content)

        # Calculate size reduction
        original_size = len(content)
        new_size = len(cleaned_content)
        size_reduction = original_size - new_size
        reduction_percentage = (size_reduction / original_size) * 100 if original_size > 0 else 0

        return {
            "input_file": str(input_path),
            "output_file": str(output_file),
            "total_vcards": len(vcards),
            "ios_entries": ios_entries_count,
            "cleaned_entries": cleaned_count,
            "original_size": original_size,
            "new_size": new_size,
            "size_reduction": size_reduction,
            "reduction_percentage": reduction_percentage,
        }

    def split_contacts_to_files(
        self,
        input_file,
        output_dir=None,
        process_photos=True,
        normalize_types=True,
        fix_preferences=True,
    ):
        """Split VCard file into individual contact files.

        Args:
            input_file: Path to the input VCard file
            output_dir: Directory to save individual contact files
            process_photos: Whether to process and resize photos
            normalize_types: Whether to normalize TYPE parameters
            fix_preferences: Whether to fix preference conflicts

        Returns:
            Dictionary with split operation statistics
        """
        input_path = Path(input_file)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")

        # Set output directory
        if output_dir:
            output_path = Path(output_dir)
        else:
            output_path = input_path.parent / f"{input_path.stem}_split"

        # Create output directory
        output_path.mkdir(parents=True, exist_ok=True)

        print(f"Reading VCard file: {input_file}")

        # Read and parse the VCard file
        with open(input_path, "r", encoding="utf-8") as f:
            content = f.read()

        print(f"File size: {len(content):,} characters")

        # Split into individual VCards
        vcards = self.split_vcards(content)
        print(f"Found {len(vcards)} VCard entries")

        # Process each VCard and save to individual files
        ios_entries_count = 0
        cleaned_count = 0
        created_files = []

        for i, vcard in enumerate(vcards, 1):
            # Check if it's an iOS entry
            if self.is_ios_entry(vcard):
                ios_entries_count += 1
                print(f"Processing iOS entry {i}...")

            # Clean the VCard (includes photo processing, type normalization,
            # preference fixing, and RFC2426 compliance if enabled)
            cleaned_vcard = self.clean_vcard_entry(
                vcard,
                process_photos,
                normalize_types,
                fix_preferences,
                ensure_rfc6350=True,
            )

            if cleaned_vcard != vcard:
                cleaned_count += 1

            # Generate filename based on contact name
            contact_name = self._extract_contact_name(cleaned_vcard)
            safe_name = self._make_safe_filename(contact_name)
            output_file = output_path / f"{safe_name}.vcf"

            # Handle filename conflicts
            counter = 1
            original_output_file = output_file
            while output_file.exists():
                output_file = original_output_file.with_stem(f"{original_output_file.stem}_{counter}")
                counter += 1

            # Write the individual contact file
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(cleaned_vcard)

            created_files.append(str(output_file))

        # Calculate statistics
        original_size = len(content)
        total_new_size = sum(len(Path(f).read_text(encoding="utf-8")) for f in created_files)
        size_reduction = original_size - total_new_size
        reduction_percentage = (size_reduction / original_size) * 100 if original_size > 0 else 0

        return {
            "input_file": str(input_path),
            "output_dir": str(output_path),
            "total_vcards": len(vcards),
            "ios_entries": ios_entries_count,
            "cleaned_entries": cleaned_count,
            "created_files": created_files,
            "files_created": len(created_files),
            "original_size": original_size,
            "new_size": total_new_size,
            "size_reduction": size_reduction,
            "reduction_percentage": reduction_percentage,
        }

    def _extract_contact_name(self, vcard_text):
        """Extract the contact name from a VCard for use as filename.

        Args:
            vcard_text: The VCard entry text

        Returns:
            String suitable for use as a filename
        """
        lines = vcard_text.split("\n")

        # First try to get the formatted name (FN)
        for line in lines:
            if line.upper().startswith("FN:"):
                name = line[3:].strip()
                if name:
                    return name

        # If no FN, try to construct from N (structured name)
        for line in lines:
            if line.upper().startswith("N:"):
                # N format: Family;Given;Middle;Prefix;Suffix
                parts = line[2:].split(";")
                name_parts = []
                if len(parts) > 1 and parts[1]:  # Given name
                    name_parts.append(parts[1])
                if len(parts) > 0 and parts[0]:  # Family name
                    name_parts.append(parts[0])
                if name_parts:
                    return " ".join(name_parts)

        # If no name found, try email
        for line in lines:
            if line.upper().startswith("EMAIL"):
                email_match = re.search(r":(.+)$", line)
                if email_match:
                    email = email_match.group(1).strip()
                    # Use the part before @ as name
                    return email.split("@")[0]

        # Last resort: use UID or generate a generic name
        for line in lines:
            if line.upper().startswith("UID:"):
                uid = line[4:].strip()
                if uid:
                    return f"Contact_{uid[:8]}"

        return "Unknown_Contact"

    def _make_safe_filename(self, name):
        """Convert a name to a safe filename.

        Args:
            name: The contact name

        Returns:
            Safe filename string
        """
        # Remove or replace unsafe characters
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", name)
        safe_name = re.sub(r"\s+", "_", safe_name)  # Replace spaces with underscores
        safe_name = safe_name.strip("._")  # Remove leading/trailing dots and underscores

        # Limit length
        if len(safe_name) > 50:
            safe_name = safe_name[:50]

        # Ensure it's not empty
        if not safe_name:
            safe_name = "Contact"

        return safe_name


def main():
    """Main function to run the VCard cleaner."""
    parser = argparse.ArgumentParser(
        description=(
            "Clean up and modernize VCard files to vCard 4.0 (RFC 6350) "
            "standard with UTF-8 encoding and ISO 8601 dates."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s contacts.vcf                     # Clean with auto-generated output filename
  %(prog)s contacts.vcf cleaned.vcf         # Specify output file
  %(prog)s --split contacts.vcf             # Split into individual contact files
  %(prog)s --split --output-dir ./contacts contacts.vcf  # Split with custom output directory

Features:
  - Upgrade to vCard 4.0 (RFC 6350) format
  - Enforce UTF-8 encoding (default in vCard 4.0)
  - Convert dates/timestamps to ISO 8601 format
  - Remove iOS ITEM prefixes (ITEM1.EMAIL -> EMAIL)
  - Normalize TYPE parameters to lowercase (vCard 4.0 style)
  - Remove obsolete parameters (CHARSET, etc.)
  - Process and resize large photos
  - Clean address fields (remove \\n sequences)
  - Remove duplicate photos (keep only first)
  - Generate new UIDs and set vCard 4.0 PRODID
  - Ensure RFC 6350 compliance
        """,
    )

    # Required arguments
    parser.add_argument(
        "input_file",
        help="Input VCard file (.vcf) to clean",
    )

    parser.add_argument(
        "output_file",
        nargs="?",
        help="Output VCard file (default: auto-generated based on input filename)",
    )

    parser.add_argument(
        "--split",
        action="store_true",
        help="Split contacts into individual VCard files",
    )

    parser.add_argument(
        "--output-dir",
        help="Output directory for split files (default: same as input file directory)",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="VCard Cleaner v2.0",
    )

    args = parser.parse_args()

    # Set up the cleaner and run
    cleaner = VCardCleaner()

    try:
        if args.split:
            # Split contacts into individual files
            print("Starting VCard split and cleanup...")
            print()

            result = cleaner.split_contacts_to_files(
                args.input_file,
                args.output_dir,
                process_photos=True,
                normalize_types=True,
                fix_preferences=True,
            )

            print("\nVCard split completed successfully!")
            print("=" * 50)
            print(f"Input file: {result['input_file']}")
            print(f"Output directory: {result['output_dir']}")
            print(f"Total VCards processed: {result['total_vcards']}")
            print(f"Individual files created: {result['files_created']}")
            print(f"iOS entries found: {result['ios_entries']}")
            print(f"Entries cleaned: {result['cleaned_entries']}")

            print("\nFile size reduction:")
            print(f"Original size: {result['original_size']:,} characters")
            print(f"New total size: {result['new_size']:,} characters")
            print(f"Reduction: {result['size_reduction']:,} characters ({result['reduction_percentage']:.1f}%)")

        else:
            # Clean to a single file
            print("Starting VCard cleanup...")
            print()

            result = cleaner.clean_vcard_file(
                args.input_file,
                args.output_file,
                process_photos=True,
                normalize_types=True,
                fix_preferences=True,
            )

            print("\nVCard cleaning completed successfully!")
            print("=" * 50)
            print(f"Input file: {result['input_file']}")
            print(f"Output file: {result['output_file']}")
            print(f"Total VCards processed: {result['total_vcards']}")
            print(f"iOS entries found: {result['ios_entries']}")
            print(f"Entries cleaned: {result['cleaned_entries']}")

            print("\nFile size reduction:")
            print(f"Original size: {result['original_size']:,} characters")
            print(f"New size: {result['new_size']:,} characters")
            print(f"Reduction: {result['size_reduction']:,} characters ({result['reduction_percentage']:.1f}%)")

    except Exception as e:
        print(f"Error processing VCard file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""
Synthetic Document Generator for Training Data.

Generates synthetic identity documents with ground truth region annotations
for training the Faster R-CNN document region detector.

Supports all document types: passport, visa, national_id, driving_license, permit.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

DocumentType = Literal["passport", "visa", "national_id", "driving_license", "permit"]

# Font paths - try to find system fonts
DEFAULT_FONTS = [
    "cour.ttf",           # Courier New (Windows)
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",  # Linux
    "/System/Library/Fonts/Courier.dfont",  # macOS
]

# Region colors for visualization (BGR)
REGION_COLORS = {
    "photo": (255, 0, 0),           # Blue
    "name": (0, 255, 0),            # Green
    "surname": (0, 255, 255),       # Yellow
    "date_of_birth": (255, 0, 255), # Magenta
    "date_of_issue": (255, 255, 0), # Cyan
    "date_of_expiry": (128, 0, 128),# Purple
    "document_number": (0, 128, 255),# Orange
    "nationality": (0, 255, 128),   # Spring green
    "mrz": (255, 128, 0),           # Light blue
    "signature": (128, 128, 128),   # Gray
    "stamp": (0, 0, 255),           # Red
}


#: Photo placeholder geometry for the synthetic canvases, as
#: ``(width, height, right_margin, top)``.  These are the plain 900x600 mock
#: documents this module draws, *not* the real Indian cards, so the measured
#: holders in ``photo_regions.REGIONS`` deliberately do not apply here.
SYNTHETIC_PHOTO_BOX = (180, 220, 220, 80)
PHOTO_FILL = (200, 200, 200)
PHOTO_OUTLINE = (100, 100, 100)


def photo_box(canvas_width: int) -> tuple[int, int, int, int]:
    """``(x, y, w, h)`` of the photo holder on a synthetic canvas."""
    w, h, right, top = SYNTHETIC_PHOTO_BOX
    return canvas_width - right, top, w, h


def draw_photo_placeholder(
    draw,
    annotations: list,
    canvas_width: int,
    font=None,
) -> None:
    """Draw the grey photo box and record its annotation.

    Was previously repeated verbatim in all five document generators; they all
    wanted the same box, so it now lives here once.
    """
    x, y, w, h = photo_box(canvas_width)
    draw.rectangle([x, y, x + w, y + h], outline=PHOTO_OUTLINE, width=2, fill=PHOTO_FILL)
    if font is not None:
        draw.text((x + 40, y + 100), "PHOTO", fill=PHOTO_OUTLINE, font=font)
    annotations.append(RegionAnnotation("photo", (x, y, w, h)))


@dataclass
class RegionAnnotation:
    """Ground truth region annotation for a synthetic document."""
    class_name: str
    bbox: tuple[int, int, int, int]  # x, y, w, h
    text: str | None = None


@dataclass
class SyntheticDocument:
    """A generated synthetic document with image and annotations."""
    image: np.ndarray
    annotations: list[RegionAnnotation]
    document_type: DocumentType
    metadata: dict = field(default_factory=dict)


class SyntheticDocumentGenerator:
    """
    Generates synthetic identity documents with region annotations.
    
    Uses PIL to render text and shapes, then converts to OpenCV format.
    Produces ground truth bounding boxes for each semantic region.
    """
    
    def __init__(
        self,
        image_size: tuple[int, int] = (900, 600),
        font_size: int = 24,
        font_path: str | None = None,
    ):
        self.image_size = image_size  # (width, height)
        self.font_size = font_size
        self.font_path = self._find_font(font_path)
        self.w, self.h = image_size
    
    def _find_font(self, font_path: str | None) -> str | None:
        if font_path and Path(font_path).exists():
            return font_path
        for fp in DEFAULT_FONTS:
            if Path(fp).exists():
                return fp
        # Fallback to default PIL font
        return None
    
    def _get_font(self, size: int | None = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        size = size or self.font_size
        if self.font_path:
            try:
                return ImageFont.truetype(self.font_path, size)
            except Exception:
                pass
        return ImageFont.load_default()
    
    def generate(
        self,
        document_type: DocumentType = "passport",
        seed: int | None = None,
    ) -> SyntheticDocument:
        """Generate a synthetic document of the specified type."""
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
        
        if document_type == "passport":
            return self._generate_passport()
        elif document_type == "visa":
            return self._generate_visa()
        elif document_type == "national_id":
            return self._generate_national_id()
        elif document_type == "driving_license":
            return self._generate_driving_license()
        elif document_type == "permit":
            return self._generate_permit()
        else:
            raise ValueError(f"Unknown document type: {document_type}")
    
    def _to_int_bbox(self, bbox: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
        """Convert float bbox to int bbox."""
        return (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
    
    def _generate_passport(self) -> SyntheticDocument:
        """Generate a synthetic passport (ICAO TD3 format)."""
        img = Image.new("RGB", self.image_size, color=(245, 245, 240))
        draw = ImageDraw.Draw(img)
        annotations: list[RegionAnnotation] = []
        
        font = self._get_font(28)
        font_small = self._get_font(20)
        font_mrz = self._get_font(18)
        
        y_pos = 30
        
        # Header
        header_text = "REPUBLIC OF UTOPIA - PASSPORT"
        draw.text((30, y_pos), header_text, fill=(0, 0, 0), font=font)
        y_pos += 50
        
        # Visual zone fields
        # Photo region (right side, upper portion)
        draw_photo_placeholder(draw, annotations, self.w, font=font_small)
        
        # Name fields (left side)
        name_x = 30
        name_y = y_pos
        
        # Surname
        surname_text = "ERIKSSON"
        draw.text((name_x, name_y), "Surname:", fill=(0, 0, 0), font=font_small)
        draw.text((name_x + 100, name_y), surname_text, fill=(0, 0, 0), font=font)
        bbox = draw.textbbox((name_x + 100, name_y), surname_text, font=font)
        annotations.append(RegionAnnotation("surname", self._to_int_bbox((bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1])), surname_text))
        name_y += 40
        
        # Given names
        given_text = "ANNA MARIA"
        draw.text((name_x, name_y), "Given Names:", fill=(0, 0, 0), font=font_small)
        draw.text((name_x + 130, name_y), given_text, fill=(0, 0, 0), font=font)
        bbox = draw.textbbox((name_x + 130, name_y), given_text, font=font)
        annotations.append(RegionAnnotation("name", self._to_int_bbox((bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1])), given_text))
        name_y += 40
        
        # Nationality
        nat_text = "UTO"
        draw.text((name_x, name_y), "Nationality:", fill=(0, 0, 0), font=font_small)
        draw.text((name_x + 130, name_y), nat_text, fill=(0, 0, 0), font=font)
        bbox = draw.textbbox((name_x + 130, name_y), nat_text, font=font)
        annotations.append(RegionAnnotation("nationality", self._to_int_bbox((bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1])), nat_text))
        name_y += 40
        
        # Date of birth
        dob_text = "12.08.1974"
        draw.text((name_x, name_y), "Date of Birth:", fill=(0, 0, 0), font=font_small)
        draw.text((name_x + 130, name_y), dob_text, fill=(0, 0, 0), font=font)
        bbox = draw.textbbox((name_x + 130, name_y), dob_text, font=font)
        annotations.append(RegionAnnotation("date_of_birth", self._to_int_bbox((bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1])), dob_text))
        name_y += 40
        
        # Document number
        doc_num = "L898902C3"
        draw.text((name_x, name_y), "Passport No:", fill=(0, 0, 0), font=font_small)
        draw.text((name_x + 130, name_y), doc_num, fill=(0, 0, 0), font=font)
        bbox = draw.textbbox((name_x + 130, name_y), doc_num, font=font)
        annotations.append(RegionAnnotation("document_number", self._to_int_bbox((bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1])), doc_num))
        name_y += 40
        
        # Date of issue
        doi_text = "15.04.2012"
        draw.text((name_x, name_y), "Date of Issue:", fill=(0, 0, 0), font=font_small)
        draw.text((name_x + 130, name_y), doi_text, fill=(0, 0, 0), font=font)
        bbox = draw.textbbox((name_x + 130, name_y), doi_text, font=font)
        annotations.append(RegionAnnotation("date_of_issue", self._to_int_bbox((bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1])), doi_text))
        name_y += 40
        
        # Date of expiry
        doe_text = "14.04.2022"
        draw.text((name_x, name_y), "Date of Expiry:", fill=(0, 0, 0), font=font_small)
        draw.text((name_x + 130, name_y), doe_text, fill=(0, 0, 0), font=font)
        bbox = draw.textbbox((name_x + 130, name_y), doe_text, font=font)
        annotations.append(RegionAnnotation("date_of_expiry", self._to_int_bbox((bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1])), doe_text))
        name_y += 60
        
        # Signature region
        sig_x = 30
        sig_y = name_y
        draw.text((sig_x, sig_y), "Signature:", fill=(0, 0, 0), font=font_small)
        draw.line([(sig_x + 100, sig_y + 25), (sig_x + 300, sig_y + 25)], fill=(0, 0, 0), width=1)
        annotations.append(RegionAnnotation("signature", (sig_x + 100, sig_y, 200, 30)))
        name_y += 50
        
        # MRZ lines (bottom of page)
        mrz_y = self.h - 80
        line1 = "P<UTOERIKSSON<<ANNA<MARIA".ljust(44, "<")
        line2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
        
        draw.text((30, mrz_y), line1, fill=(0, 0, 0), font=font_mrz)
        draw.text((30, mrz_y + 30), line2, fill=(0, 0, 0), font=font_mrz)
        
        # MRZ region covers both lines
        mrz_bbox = (30, mrz_y - 5, self.w - 60, 65)
        annotations.append(RegionAnnotation("mrz", mrz_bbox, f"{line1}\n{line2}"))
        
        # Convert to OpenCV format
        cv_image = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        
        return SyntheticDocument(
            image=cv_image,
            annotations=annotations,
            document_type="passport",
            metadata={
                "mrz_line1": line1,
                "mrz_line2": line2,
                "fields": {
                    "surname": "ERIKSSON",
                    "given_names": "ANNA MARIA",
                    "nationality": "UTO",
                    "date_of_birth": "1974-08-12",
                    "date_of_issue": "2012-04-15",
                    "date_of_expiry": "2022-04-14",
                    "passport_number": "L898902C3",
                }
            }
        )
    
    def _generate_visa(self) -> SyntheticDocument:
        """Generate a synthetic visa."""
        img = Image.new("RGB", self.image_size, color=(245, 245, 240))
        draw = ImageDraw.Draw(img)
        annotations = []
        
        font = self._get_font(28)
        font_small = self._get_font(20)
        
        y_pos = 30
        draw.text((30, y_pos), "REPUBLIC OF UTOPIA - VISA", fill=(0, 0, 0), font=font)
        y_pos += 50
        
        # Photo
        draw_photo_placeholder(draw, annotations, self.w)
        
        # Fields
        name_x = 30
        name_y = y_pos
        
        fields_data = [
            ("name", "Given Names:", "JOHN DOE"),
            ("surname", "Surname:", "SMITH"),
            ("nationality", "Nationality:", "USA"),
            ("date_of_birth", "Date of Birth:", "01.01.1990"),
            ("document_number", "Visa No:", "V1234567"),
        ]
        
        for class_name, label, value in fields_data:
            draw.text((name_x, name_y), label, fill=(0, 0, 0), font=font_small)
            draw.text((name_x + 150, name_y), value, fill=(0, 0, 0), font=font)
            bbox = draw.textbbox((name_x + 150, name_y), value, font=font)
            annotations.append(RegionAnnotation(class_name, self._to_int_bbox((bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1])), value))
            name_y += 40
        
        # Stamp region (lower right)
        stamp_x = self.w - 250
        stamp_y = self.h - 200
        stamp_w = 200
        stamp_h = 150
        draw.ellipse([stamp_x, stamp_y, stamp_x + stamp_w, stamp_y + stamp_h], outline=(200, 0, 0), width=3)
        draw.text((stamp_x + 30, stamp_y + 60), "STAMP", fill=(200, 0, 0), font=font)
        annotations.append(RegionAnnotation("stamp", (stamp_x, stamp_y, stamp_w, stamp_h)))
        
        # MRZ for visa (TD1 format - 3 lines)
        mrz_y = self.h - 120
        visa_mrz = [
            "I<UTO1234567890<<<<<<<<<<<<<<<",
            "7408122F1204159UTO<<<<<<<<<<<6",
            "SMITH<<JOHN<<<<<<<<<<<<<<<<<<<",
        ]
        for i, line in enumerate(visa_mrz):
            draw.text((30, mrz_y + i * 25), line, fill=(0, 0, 0), font=font_small)
        annotations.append(RegionAnnotation("mrz", (30, mrz_y - 5, self.w - 60, 80), "\n".join(visa_mrz)))
        
        cv_image = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        
        return SyntheticDocument(
            image=cv_image,
            annotations=annotations,
            document_type="visa",
        )
    
    def _generate_national_id(self) -> SyntheticDocument:
        """Generate a synthetic national ID card."""
        img = Image.new("RGB", self.image_size, color=(245, 245, 240))
        draw = ImageDraw.Draw(img)
        annotations = []
        
        font = self._get_font(28)
        font_small = self._get_font(20)
        
        y_pos = 30
        draw.text((30, y_pos), "REPUBLIC OF UTOPIA - NATIONAL ID", fill=(0, 0, 0), font=font)
        y_pos += 50
        
        # Photo
        draw_photo_placeholder(draw, annotations, self.w)
        
        name_x = 30
        name_y = y_pos
        
        fields_data = [
            ("name", "Name:", "RAJESH KUMAR"),
            ("surname", "Surname:", "SHARMA"),
            ("document_number", "ID No:", "IN123456789012"),
            ("date_of_birth", "DOB:", "15.08.1985"),
            ("nationality", "Nationality:", "IND"),
        ]
        
        for class_name, label, value in fields_data:
            draw.text((name_x, name_y), label, fill=(0, 0, 0), font=font_small)
            draw.text((name_x + 130, name_y), value, fill=(0, 0, 0), font=font)
            bbox = draw.textbbox((name_x + 130, name_y), value, font=font)
            annotations.append(RegionAnnotation(class_name, self._to_int_bbox((bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1])), value))
            name_y += 40
        
        cv_image = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        
        return SyntheticDocument(
            image=cv_image,
            annotations=annotations,
            document_type="national_id",
        )
    
    def _generate_driving_license(self) -> SyntheticDocument:
        """Generate a synthetic driving license."""
        img = Image.new("RGB", self.image_size, color=(245, 245, 240))
        draw = ImageDraw.Draw(img)
        annotations = []
        
        font = self._get_font(28)
        font_small = self._get_font(20)
        
        y_pos = 30
        draw.text((30, y_pos), "REPUBLIC OF UTOPIA - DRIVING LICENSE", fill=(0, 0, 0), font=font)
        y_pos += 50
        
        # Photo
        draw_photo_placeholder(draw, annotations, self.w)
        
        name_x = 30
        name_y = y_pos
        
        fields_data = [
            ("name", "Name:", "ALEXANDER MUELLER"),
            ("surname", "Surname:", "MUELLER"),
            ("document_number", "DL No:", "DL987654321"),
            ("date_of_birth", "DOB:", "20.03.1992"),
            ("date_of_issue", "Issue Date:", "10.01.2018"),
            ("date_of_expiry", "Expiry:", "09.01.2033"),
            ("nationality", "Nationality:", "DEU"),
        ]
        
        for class_name, label, value in fields_data:
            draw.text((name_x, name_y), label, fill=(0, 0, 0), font=font_small)
            draw.text((name_x + 130, name_y), value, fill=(0, 0, 0), font=font)
            bbox = draw.textbbox((name_x + 130, name_y), value, font=font)
            annotations.append(RegionAnnotation(class_name, self._to_int_bbox((bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1])), value))
            name_y += 40
        
        cv_image = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        
        return SyntheticDocument(
            image=cv_image,
            annotations=annotations,
            document_type="driving_license",
        )
    
    def _generate_permit(self) -> SyntheticDocument:
        """Generate a synthetic permit."""
        img = Image.new("RGB", self.image_size, color=(245, 245, 240))
        draw = ImageDraw.Draw(img)
        annotations = []
        
        font = self._get_font(28)
        font_small = self._get_font(20)
        
        y_pos = 30
        draw.text((30, y_pos), "REPUBLIC OF UTOPIA - PERMIT", fill=(0, 0, 0), font=font)
        y_pos += 50
        
        # Photo
        draw_photo_placeholder(draw, annotations, self.w)
        
        name_x = 30
        name_y = y_pos
        
        fields_data = [
            ("name", "Holder:", "MARIA GARCIA"),
            ("document_number", "Permit No:", "PMT555666"),
            ("permit_type", "Type:", "Work Permit"),
            ("date_of_birth", "DOB:", "12.11.1988"),
            ("date_of_issue", "Valid From:", "01.01.2024"),
            ("date_of_expiry", "Valid Till:", "31.12.2025"),
        ]
        
        for class_name, label, value in fields_data:
            draw.text((name_x, name_y), label, fill=(0, 0, 0), font=font_small)
            draw.text((name_x + 130, name_y), value, fill=(0, 0, 0), font=font)
            bbox = draw.textbbox((name_x + 130, name_y), value, font=font)
            annotations.append(RegionAnnotation(class_name, self._to_int_bbox((bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1])), value))
            name_y += 40
        
        cv_image = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        
        return SyntheticDocument(
            image=cv_image,
            annotations=annotations,
            document_type="permit",
        )
    
    def generate_batch(
        self,
        document_type: DocumentType = "passport",
        count: int = 100,
        output_dir: str | Path | None = None,
    ) -> list[SyntheticDocument]:
        """Generate a batch of synthetic documents."""
        documents = []
        for i in range(count):
            doc = self.generate(document_type, seed=i)
            documents.append(doc)
            
            if output_dir:
                out_path = Path(output_dir)
                out_path.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(out_path / f"{document_type}_{i:04d}.png"), doc.image)
                # Save annotations as JSON
                import json
                ann_path = out_path / f"{document_type}_{i:04d}_annotations.json"
                with open(ann_path, "w") as f:
                    json.dump([{
                        "class_name": a.class_name,
                        "bbox": a.bbox,
                        "text": a.text,
                    } for a in doc.annotations], f)
        
        return documents
    
    def visualize_annotations(self, doc: SyntheticDocument) -> np.ndarray:
        """Draw annotations on image for visualization."""
        vis = doc.image.copy()
        for ann in doc.annotations:
            color = REGION_COLORS.get(ann.class_name, (255, 255, 255))
            x, y, w, h = ann.bbox
            cv2.rectangle(vis, (x, y), (x + w, y + h), color, 2)
            cv2.putText(vis, ann.class_name, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        return vis


def create_generator(
    image_size: tuple[int, int] = (900, 600),
    font_size: int = 24,
) -> SyntheticDocumentGenerator:
    """Factory function to create a synthetic document generator."""
    return SyntheticDocumentGenerator(image_size=image_size, font_size=font_size)
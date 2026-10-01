"""
Faster R-CNN based Document Region Localization.

Detects semantically meaningful regions of identity documents:
- photo: The portrait photo of the document holder
- name/given_names/surname: Text fields for personal names
- date_of_birth: Date of birth field
- date_of_issue: Document issue date
- date_of_expiry: Document expiry date
- document_number: Document/passport/visa/license number
- nationality: Nationality/country code field
- mrz: Machine Readable Zone (ICAO TD3/TD1)
- signature: Signature region
- stamp: Visa/entry stamp region

This runs BEFORE OCR/MRZ/face/tampering modules and provides
region coordinates for targeted processing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Document region class labels (background=0 is implicit)
REGION_CLASSES = [
    "background",      # 0
    "photo",           # 1 - Portrait photo
    "name",            # 2 - Full name or given name
    "surname",         # 3 - Surname/family name
    "date_of_birth",   # 4 - DOB field
    "date_of_issue",   # 5 - Issue date field
    "date_of_expiry",  # 6 - Expiry date field
    "document_number", # 7 - Document/passport/visa/license number
    "nationality",     # 8 - Nationality/country code
    "mrz",             # 9 - Machine Readable Zone
    "signature",       # 10 - Signature region
    "stamp",           # 11 - Visa/entry stamp
    "address",         # 12 - Postal address block
    "guardian_name",   # 13 - Father's / S/D/W-of name
    "place_of_birth",  # 14
    "gender",          # 15
    "qr_code",         # 16 - Aadhaar / PAN QR
    "barcode",         # 17 - Passport barcode
]

# Per-document-type region relevance (which regions to expect)
DOCUMENT_TYPE_REGIONS = {
    "passport": [
        "photo", "name", "surname", "date_of_birth", 
        "date_of_issue", "date_of_expiry", "document_number",
        "nationality", "mrz", "signature", "address", "guardian_name",
        "place_of_birth", "gender", "barcode"
    ],
    "visa": [
        "photo", "name", "surname", "date_of_birth",
        "date_of_issue", "date_of_expiry", "document_number",
        "nationality", "stamp"
    ],
    "national_id": [
        "photo", "name", "surname", "date_of_birth",
        "document_number", "nationality"
    ],
    "driving_license": [
        "photo", "name", "surname", "date_of_birth",
        "date_of_issue", "date_of_expiry", "document_number",
        "nationality", "address", "guardian_name"
    ],
    "aadhar": ["photo", "name", "date_of_birth", "document_number", "address", "gender", "qr_code"],
    "aadhaar": ["photo", "name", "date_of_birth", "document_number", "address", "gender", "qr_code"],
    "pan": ["photo", "name", "guardian_name", "date_of_birth", "document_number", "qr_code"],
    "permit": [
        "photo", "name", "date_of_birth",
        "date_of_issue", "date_of_expiry", "document_number"
    ],
}

# Default confidence thresholds per class
DEFAULT_CONFIDENCE_THRESHOLDS = {
    "photo": 0.5,
    "name": 0.4,
    "surname": 0.4,
    "date_of_birth": 0.4,
    "date_of_issue": 0.4,
    "date_of_expiry": 0.4,
    "document_number": 0.4,
    "nationality": 0.4,
    "mrz": 0.5,
    "signature": 0.3,
    "stamp": 0.4,
}


@dataclass
class DocumentRegion:
    """A detected document region with class, bounding box, and confidence."""
    class_id: int
    class_name: str
    bbox: tuple[int, int, int, int]  # x, y, w, h (absolute pixels)
    confidence: float
    
    @property
    def x(self) -> int:
        return self.bbox[0]
    
    @property
    def y(self) -> int:
        return self.bbox[1]
    
    @property
    def w(self) -> int:
        return self.bbox[2]
    
    @property
    def h(self) -> int:
        return self.bbox[3]
    
    def to_dict(self) -> dict:
        return {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "bbox": {"x": self.x, "y": self.y, "w": self.w, "h": self.h},
            "confidence": round(self.confidence, 3),
        }
    
    def crop(self, image: np.ndarray) -> np.ndarray:
        """Crop the region from an image."""
        x, y, w, h = self.bbox
        return image[y:y+h, x:x+w]


@dataclass
class RegionDetectionResult:
    """Complete region detection result for a document image."""
    regions: list[DocumentRegion] = field(default_factory=list)
    document_type: str | None = None
    image_shape: tuple[int, int] | None = None  # (height, width)
    preprocessing_applied: bool = False
    model_version: str = "fasterrcnn_resnet50_fpn_v1"
    
    def get_regions_by_class(self, class_name: str) -> list[DocumentRegion]:
        """Get all regions matching a class name."""
        return [r for r in self.regions if r.class_name == class_name]
    
    def get_best_region(self, class_name: str) -> DocumentRegion | None:
        """Get the highest-confidence region for a class."""
        regions = self.get_regions_by_class(class_name)
        if not regions:
            return None
        return max(regions, key=lambda r: r.confidence)
    
    def get_text_regions(self) -> list[DocumentRegion]:
        """Get all text field regions (for OCR)."""
        text_classes = {"name", "surname", "date_of_birth", "date_of_issue",
                        "date_of_expiry", "document_number", "nationality", "address",
                        "guardian_name", "place_of_birth", "gender"}
        return [r for r in self.regions if r.class_name in text_classes]
    
    def get_photo_region(self) -> DocumentRegion | None:
        """Get the photo region (for face verification)."""
        return self.get_best_region("photo")
    
    def get_mrz_region(self) -> DocumentRegion | None:
        """Get the MRZ region (for MRZ parser)."""
        return self.get_best_region("mrz")
    
    def get_stamp_region(self) -> DocumentRegion | None:
        """Get the stamp region (for visa stamp verification)."""
        return self.get_best_region("stamp")
    
    def to_dict(self) -> dict:
        return {
            "document_type": self.document_type,
            "image_shape": self.image_shape,
            "preprocessing_applied": self.preprocessing_applied,
            "model_version": self.model_version,
            "regions": [r.to_dict() for r in self.regions],
        }


class DocumentRegionDetector:
    """
    Faster R-CNN based document region detector.
    
    Uses torchvision's Faster R-CNN with ResNet50-FPN backbone.
    Can be trained on synthetic data and fine-tuned on real documents.
    """
    
    def __init__(
        self,
        model_path: str | Path | None = None,
        confidence_threshold: float = 0.5,
        device: str = "cpu",
        num_classes: int = len(REGION_CLASSES),
    ):
        self.model_path = Path(model_path) if model_path else None
        self.confidence_threshold = confidence_threshold
        self.device = device
        self.num_classes = num_classes
        self._model = None
        self._initialized = False
        self.classes = list(REGION_CLASSES)
    
    def _lazy_init(self):
        """Lazy initialization of the model."""
        if self._initialized:
            return
        
        try:
            import torch
            import torchvision
            from torchvision.models.detection import fasterrcnn_resnet50_fpn_v2
            from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
            
            checkpoint = None
            if self.model_path and self.model_path.exists():
                checkpoint = torch.load(self.model_path, map_location=self.device, weights_only=True)

            if isinstance(checkpoint, dict) and "architecture" in checkpoint:
                # Checkpoint from training/train_region_detector.py: rebuild the exact
                # architecture it was trained with (wide text anchors, its class list).
                from torchvision.models.detection import fasterrcnn_resnet50_fpn
                from torchvision.models.detection.anchor_utils import AnchorGenerator
                from torchvision.models.detection.rpn import RPNHead

                arch = checkpoint["architecture"]
                sizes = tuple(tuple(s) for s in arch["anchor_sizes"])
                ratios = tuple(arch["anchor_ratios"])
                self.classes = list(checkpoint["classes"])
                self._model = fasterrcnn_resnet50_fpn(
                    weights=None, weights_backbone=None, num_classes=len(self.classes),
                    rpn_anchor_generator=AnchorGenerator(sizes, (ratios,) * len(sizes)),
                    rpn_head=RPNHead(256, len(ratios)),
                    min_size=arch["min_size"], max_size=arch["max_size"],
                )
                self._model.load_state_dict(checkpoint["model_state"])
                self.model_version = f"{arch['name']}_regions_e{checkpoint.get('epoch', '?')}"
                logger.info(f"Loaded region detector from {self.model_path} ({len(self.classes) - 1} classes)")
            else:
                self._model = fasterrcnn_resnet50_fpn_v2(weights=None)
                in_features = self._model.roi_heads.box_predictor.cls_score.in_features
                self._model.roi_heads.box_predictor = FastRCNNPredictor(in_features, self.num_classes)
                if checkpoint is not None:
                    self._model.load_state_dict(checkpoint)
                    logger.info(f"Loaded custom model from {self.model_path}")
                else:
                    logger.warning("No custom model weights loaded. Using random initialization.")

            self._model.to(self.device)
            self._model.eval()
            
            self._initialized = True
            logger.info(f"Faster R-CNN detector initialized on {self.device}")
            
        except ImportError as e:
            logger.error(f"torch/torchvision not available: {e}")
            self._initialized = False
            raise RuntimeError("torch and torchvision are required for Faster R-CNN detector")
        except Exception as e:
            logger.error(f"Failed to initialize Faster R-CNN: {e}")
            raise
    
    def detect(self, image: np.ndarray, document_type: str | None = None) -> RegionDetectionResult:
        """
        Detect document regions in an image.
        
        Args:
            image: BGR image (OpenCV format)
            document_type: Optional document type to filter expected regions
            
        Returns:
            RegionDetectionResult with detected regions
        """
        self._lazy_init()
        
        if not self._initialized or self._model is None:
            logger.warning("Detector not initialized, returning empty result")
            return RegionDetectionResult(
                regions=[],
                document_type=document_type,
                image_shape=image.shape[:2],
            )
        
        import torch
        import torchvision.transforms.functional as F
        
        # Preprocess image
        h, w = image.shape[:2]
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        # Convert to tensor and normalize
        img_tensor = torch.from_numpy(rgb_image).permute(2, 0, 1).float() / 255.0
        img_tensor = img_tensor.unsqueeze(0).to(self.device)
        
        # Run inference
        with torch.no_grad():
            predictions = self._model(img_tensor)
        
        # Parse predictions
        pred = predictions[0]
        boxes = pred["boxes"].cpu().numpy()
        labels = pred["labels"].cpu().numpy()
        scores = pred["scores"].cpu().numpy()
        
        regions = []
        for box, label, score in zip(boxes, labels, scores):
            if score < self.confidence_threshold:
                continue
            
            class_name = self.classes[label] if label < len(self.classes) else f"class_{label}"
            
            # Apply per-class threshold
            class_threshold = DEFAULT_CONFIDENCE_THRESHOLDS.get(class_name, self.confidence_threshold)
            if score < class_threshold:
                continue
            
            # Convert to (x, y, w, h)
            x1, y1, x2, y2 = (int(v) for v in box)  # plain ints: the result is serialised to JSON
            bbox = (x1, y1, x2 - x1, y2 - y1)
            
            region = DocumentRegion(
                class_id=int(label),
                class_name=class_name,
                bbox=bbox,
                confidence=float(score),
            )
            regions.append(region)
        
        # Filter by document type if provided
        if document_type and document_type in DOCUMENT_TYPE_REGIONS:
            expected_classes = set(DOCUMENT_TYPE_REGIONS[document_type])
            regions = [r for r in regions if r.class_name in expected_classes]
        
        return RegionDetectionResult(
            regions=regions,
            document_type=document_type,
            image_shape=(h, w),
            preprocessing_applied=False,
            model_version=getattr(self, "model_version", "fasterrcnn_resnet50_fpn_v1"),
        )
    
    def detect_with_preprocessing(
        self, 
        image: np.ndarray, 
        document_type: str | None = None,
        apply_deskew: bool = True,
        apply_clahe: bool = True,
    ) -> RegionDetectionResult:
        """
        Detect regions with optional preprocessing for better detection.
        """
        processed = image.copy()
        
        if apply_clahe:
            # Apply CLAHE for contrast enhancement
            lab = cv2.cvtColor(processed, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            l = clahe.apply(l)
            lab = cv2.merge((l, a, b))
            processed = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        
        if apply_deskew:
            # Simple deskew using text orientation
            processed = self._deskew_image(processed)
        
        result = self.detect(processed, document_type)
        result.preprocessing_applied = True
        return result
    
    def _deskew_image(self, image: np.ndarray) -> np.ndarray:
        """Simple deskew using text line detection."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Threshold
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return image
        
        # Find the largest contour (likely the document)
        largest = max(contours, key=cv2.contourArea)
        rect = cv2.minAreaRect(largest)
        angle = rect[-1]
        
        if angle < -45:
            angle = 90 + angle
        
        if abs(angle) > 0.5:
            h, w = image.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            return rotated
        
        return image

    def detect_from_annotations(
        self, 
        image: np.ndarray, 
        annotations: list,
        document_type: str | None = None
    ) -> RegionDetectionResult:
        """
        Create detection result from ground truth annotations (for testing).
        
        Args:
            image: Source image
            annotations: List of RegionAnnotation objects from synthetic generator
            document_type: Optional document type for filtering
            
        Returns:
            RegionDetectionResult with regions from annotations
        """
        h, w = image.shape[:2]
        regions = []
        
        for ann in annotations:
            # Filter by document type if provided
            if document_type and document_type in DOCUMENT_TYPE_REGIONS:
                expected_classes = set(DOCUMENT_TYPE_REGIONS[document_type])
                if ann.class_name not in expected_classes:
                    continue
            
            region = DocumentRegion(
                class_id=REGION_CLASSES.index(ann.class_name) if ann.class_name in REGION_CLASSES else 0,
                class_name=ann.class_name,
                bbox=ann.bbox,
                confidence=1.0,  # Ground truth has perfect confidence
            )
            regions.append(region)
        
        return RegionDetectionResult(
            regions=regions,
            document_type=document_type,
            image_shape=(h, w),
            preprocessing_applied=False,
        )


def create_detector(
    model_path: str | Path | None = None,
    confidence_threshold: float = 0.5,
    device: str = "cpu",
) -> DocumentRegionDetector:
    """Factory function to create a document region detector."""
    return DocumentRegionDetector(
        model_path=model_path,
        confidence_threshold=confidence_threshold,
        device=device,
    )
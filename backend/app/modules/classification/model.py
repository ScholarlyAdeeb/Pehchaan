import torch.nn as nn
import torchvision.models as models

class DocumentClassifier(nn.Module):
    def __init__(self, num_classes=3):
        super(DocumentClassifier, self).__init__()
        # Use a lightweight pretrained model
        self.backbone = models.mobilenet_v2(weights="IMAGENET1K_V1")
        # Replace the final classifier
        # Access the Linear layer inside the Sequential classifier
        num_ftrs = self.backbone.classifier[1].in_features  # type: ignore
        self.backbone.classifier[1] = nn.Linear(num_ftrs, num_classes)

    def forward(self, x):
        return self.backbone(x)

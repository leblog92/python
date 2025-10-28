import cv2
import numpy as np
import os
from PIL import Image

class CustomMaskApp:
    def __init__(self, mask_folder="masks"):
        # Initialize OpenCV face detector
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
        # Initialize webcam
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        # Load custom masks from folder
        self.mask_folder = mask_folder
        self.masks = self.load_custom_masks()
        self.current_mask_index = 0
        
        if not self.masks:
            print(f"Error: No PNG files found in '{mask_folder}' folder!")
            print("Please add PNG mask files to the folder and restart the program.")
            self.cap.release()
            exit()
    
    def load_custom_masks(self):
        """Load PNG masks from the specified folder"""
        masks = []
        
        # Check if folder exists
        if not os.path.exists(self.mask_folder):
            print(f"Creating '{self.mask_folder}' folder...")
            os.makedirs(self.mask_folder)
            print(f"Please add your PNG mask files to the '{self.mask_folder}' folder and restart the program.")
            return masks
        
        # Load only PNG files
        png_files = [f for f in os.listdir(self.mask_folder) if f.lower().endswith('.png')]
        
        if not png_files:
            print(f"No PNG files found in '{self.mask_folder}' folder.")
            return masks
        
        # Load all PNG images from the folder
        for filename in png_files:
            try:
                mask_path = os.path.join(self.mask_folder, filename)
                mask = Image.open(mask_path).convert('RGBA')
                masks.append(mask)
                print(f"✓ Loaded mask: {filename} ({mask.size[0]}x{mask.size[1]})")
            except Exception as e:
                print(f"✗ Error loading {filename}: {e}")
        
        return masks
    
    def apply_monster_mask(self, frame, face_rect):
        """Apply monster mask to detected face"""
        x, y, w, h = face_rect
        
        # Ensure coordinates are within frame bounds
        x = max(0, x)
        y = max(0, y)
        w = min(w, frame.shape[1] - x)
        h = min(h, frame.shape[0] - y)
        
        if w > 0 and h > 0:
            # Calculate mask size based on face dimensions
            mask_width = int(w * 1.4)  # Adjust this multiplier to fit your masks
            mask_height = int(h * 1.4)
            mask_x = max(0, x - int(w * 0.2))
            mask_y = max(0, y - int(h * 0.2))
            
            # Resize mask while maintaining aspect ratio
            original_mask = self.masks[self.current_mask_index]
            original_width, original_height = original_mask.size
            
            # Maintain aspect ratio
            aspect_ratio = original_width / original_height
            if mask_width / mask_height > aspect_ratio:
                mask_width = int(mask_height * aspect_ratio)
            else:
                mask_height = int(mask_width / aspect_ratio)
            
            # Resize mask
            mask_resized = original_mask.resize((mask_width, mask_height), Image.Resampling.LANCZOS)
            mask_array = np.array(mask_resized)
            
            # Convert mask to BGRA for OpenCV
            mask_bgra = cv2.cvtColor(mask_array, cv2.COLOR_RGBA2BGRA)
            mask_bgr = mask_bgra[:, :, :3]
            mask_alpha = mask_bgra[:, :, 3] / 255.0
            
            # Region of interest
            roi_y_end = min(mask_y + mask_height, frame.shape[0])
            roi_x_end = min(mask_x + mask_width, frame.shape[1])
            actual_height = roi_y_end - mask_y
            actual_width = roi_x_end - mask_x
            
            if actual_height > 0 and actual_width > 0:
                roi = frame[mask_y:roi_y_end, mask_x:roi_x_end]
                
                # Resize mask parts to match ROI
                mask_bgr_resized = mask_bgr[:actual_height, :actual_width]
                mask_alpha_resized = mask_alpha[:actual_height, :actual_width]
                
                # Blend mask with ROI using alpha channel
                for c in range(3):
                    roi[:, :, c] = (mask_bgr_resized[:, :, c] * mask_alpha_resized + 
                                   roi[:, :, c] * (1 - mask_alpha_resized))
                
                frame[mask_y:roi_y_end, mask_x:roi_x_end] = roi
        
        return frame
    
    def run(self):
        """Main application loop"""
        print("\n" + "="*60)
        print("🎭 CUSTOM MONSTER MASK APP")
        print("="*60)
        print(f"📁 Masks loaded: {len(self.masks)}")
        print("\n🎮 Controls:")
        print("  'n' - Next mask")
        print("  'p' - Previous mask")  
        print("  'q' - Quit")
        print("="*60)
        
        while True:
            ret, frame = self.cap.read()
            if not ret:
                print("Error: Could not read from webcam")
                break
            
            # Flip frame horizontally for mirror effect
            frame = cv2.flip(frame, 1)
            
            # Convert to grayscale for face detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Detect faces
            faces = self.face_cascade.detectMultiScale(
                gray, 
                scaleFactor=1.1, 
                minNeighbors=5, 
                minSize=(30, 30)
            )
            
            # Apply masks to all detected faces
            for (x, y, w, h) in faces:
                frame = self.apply_monster_mask(frame, (x, y, w, h))
            
            # Add instructions and info to frame
            cv2.putText(frame, f"Mask: {self.current_mask_index + 1}/{len(self.masks)}", 
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, f"Faces detected: {len(faces)}", 
                       (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, "Press 'n' for next, 'p' for previous", 
                       (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, "Press 'q' to quit", 
                       (10, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            # Display frame
            cv2.imshow('Custom Monster Mask App', frame)
            
            # Handle key presses
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('n'):
                self.current_mask_index = (self.current_mask_index + 1) % len(self.masks)
                print(f"Switched to mask {self.current_mask_index + 1}")
            elif key == ord('p'):
                self.current_mask_index = (self.current_mask_index - 1) % len(self.masks)
                print(f"Switched to mask {self.current_mask_index + 1}")
        
        # Cleanup
        self.cap.release()
        cv2.destroyAllWindows()
        print("App closed successfully!")

def download_sample_mask():
    """Instructions for downloading the sample mask"""
    print("\n📥 To download the monster mask from your link:")
    print("1. Go to: https://static.vecteezy.com/system/resources/previews/051/220/960/non_2x/cartoon-monster-mask-with-fangs-and-one-eye-png.png")
    print("2. Right-click on the image and select 'Save image as...'")
    print("3. Save it in the 'masks' folder as 'monster_mask.png'")
    print("4. Add more PNG files to the 'masks' folder if desired")
    print("5. Run the program again!")

if __name__ == "__main__":
    # Check if masks folder exists and has PNG files
    mask_folder = "masks"
    if not os.path.exists(mask_folder) or not any(f.lower().endswith('.png') for f in os.listdir(mask_folder) if os.path.isdir(mask_folder)):
        print("❌ No masks found!")
        download_sample_mask()
        
        # Create folder if it doesn't exist
        if not os.path.exists(mask_folder):
            os.makedirs(mask_folder)
        
        print(f"\n📁 Please add PNG files to the '{mask_folder}' folder and run the program again.")
    else:
        # Run the app
        app = CustomMaskApp(mask_folder)
        app.run()
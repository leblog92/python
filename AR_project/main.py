import cv2
import numpy as np
import pygame
from OpenGL.GL import *
from OpenGL.GLU import *
from pygame.locals import *
import sys
from ar_utils import ARRenderer

class AugmentedRealityApp:
    def __init__(self):
        # Initialisation de la caméra
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            print("Erreur: Impossible d'ouvrir la caméra")
            sys.exit(1)
        
        # Paramètres de la caméra
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        # Initialisation de Pygame et OpenGL
        self.init_pygame_opengl()
        
        # Initialisation du renderer AR
        self.ar_renderer = ARRenderer()
        
        # Initialisation du détecteur ArUco (version corrigée)
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
        self.aruco_params = cv2.aruco.DetectorParameters()
        
        # Pour OpenCV 4.7.0 et plus, utiliser ArUcoDetector
        if hasattr(cv2.aruco, 'ArucoDetector'):
            self.aruco_detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)
        else:
            self.aruco_detector = None
            
        # Variables pour les marqueurs
        self.corners = None
        self.ids = None
        
        self.running = True
        
    def init_pygame_opengl(self):
        """Initialise Pygame avec OpenGL"""
        pygame.init()
        
        # Configuration de l'affichage OpenGL
        self.screen_width = 1280
        self.screen_height = 720
        
        pygame.display.set_mode(
            (self.screen_width, self.screen_height),
            DOUBLEBUF | OPENGL
        )
        pygame.display.set_caption("AR Application avec Objets 3D")
        
        # Configuration de la perspective OpenGL
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45, (self.screen_width / self.screen_height), 0.1, 100.0)
        glMatrixMode(GL_MODELVIEW)
        
        # Paramètres de rendu
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_COLOR_MATERIAL)
        
        # Position de la lumière
        glLightfv(GL_LIGHT0, GL_POSITION, (0, 5, 5, 1))
        glLightfv(GL_LIGHT0, GL_AMBIENT, (0.3, 0.3, 0.3, 1))
        glLightfv(GL_LIGHT0, GL_DIFFUSE, (1, 1, 1, 1))
        
    def capture_frame(self):
        """Capture une frame de la caméra"""
        ret, frame = self.cap.read()
        if ret:
            return cv2.flip(frame, 1)  # Flip horizontal pour un rendu miroir
        return None
    
    def detect_markers(self, frame):
        """Détecte les marqueurs ArUco dans l'image"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Méthode de détection selon la version d'OpenCV
        if self.aruco_detector is not None:
            # Nouvelle méthode (OpenCV 4.7+)
            corners, ids, _ = self.aruco_detector.detectMarkers(gray)
        else:
            # Ancienne méthode
            corners, ids, _ = cv2.aruco.detectMarkers(gray, self.aruco_dict, parameters=self.aruco_params)
        
        return corners, ids
    
    def render_scene(self, frame, corners, ids):
        """Rendu de la scène AR"""
        # Dessiner le fond vidéo
        self.draw_video_background(frame)
        
        if ids is not None and len(ids) > 0:
            # Pour chaque marqueur détecté
            for i in range(len(ids)):
                # Calcul de la pose du marqueur
                rvec, tvec, _ = cv2.aruco.estimatePoseSingleMarkers(
                    corners[i], 0.05, self.ar_renderer.camera_matrix, 
                    self.ar_renderer.dist_coeffs
                )
                
                # Sauvegarder la position pour le rendu 3D
                self.ar_renderer.marker_positions.append((tvec[0][0], rvec[0][0]))
        
        # Rendu des objets 3D
        self.ar_renderer.render_all_objects()
        
    def draw_video_background(self, frame):
        """Dessine la vidéo en arrière-plan"""
        # Convertir l'image OpenCV pour Pygame
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_rgb = np.rot90(frame_rgb)  # Rotation pour l'orientation correcte
        frame_surface = pygame.surfarray.make_surface(frame_rgb)
        
        # Redimensionner si nécessaire
        frame_surface = pygame.transform.scale(frame_surface, (self.screen_width, self.screen_height))
        
        # Sauvegarder les états OpenGL
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, self.screen_width, self.screen_height, 0, -1, 1)
        
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        
        # Dessiner la texture
        glEnable(GL_TEXTURE_2D)
        texture_id = self.surface_to_texture(frame_surface)
        glBindTexture(GL_TEXTURE_2D, texture_id)
        
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex2f(0, 0)
        glTexCoord2f(1, 0); glVertex2f(self.screen_width, 0)
        glTexCoord2f(1, 1); glVertex2f(self.screen_width, self.screen_height)
        glTexCoord2f(0, 1); glVertex2f(0, self.screen_height)
        glEnd()
        
        glDeleteTextures([texture_id])
        glDisable(GL_TEXTURE_2D)
        
        # Restaurer les états OpenGL
        glEnable(GL_LIGHTING)
        glEnable(GL_DEPTH_TEST)
        
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glPopMatrix()
        
    def surface_to_texture(self, surface):
        """Convertit une surface Pygame en texture OpenGL"""
        try:
            texture_data = pygame.image.tostring(surface, "RGB", 1)
            width, height = surface.get_size()
            
            texture_id = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, texture_id)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, width, height, 0, GL_RGB, GL_UNSIGNED_BYTE, texture_data)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            
            return texture_id
        except Exception as e:
            print(f"Erreur lors de la création de la texture: {e}")
            return None
    
    def run(self):
        """Boucle principale de l'application"""
        clock = pygame.time.Clock()
        
        print("Application AR démarrée. Appuyez sur ÉCHAP pour quitter.")
        print("Placez un marqueur ArUco devant la caméra.")
        
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
            
            # Capture de la frame
            frame = self.capture_frame()
            if frame is None:
                continue
            
            # Détection des marqueurs
            corners, ids = self.detect_markers(frame)
            
            # Mise à jour des positions des marqueurs
            self.ar_renderer.marker_positions = []
            
            # Nettoyage de l'écran
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glLoadIdentity()
            
            # Rendu de la scène
            self.render_scene(frame, corners, ids)
            
            # Mise à jour de l'affichage
            pygame.display.flip()
            clock.tick(30)
        
        # Nettoyage
        self.cap.release()
        pygame.quit()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    app = AugmentedRealityApp()
    app.run()
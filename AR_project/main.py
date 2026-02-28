import cv2
import numpy as np
import pygame
from OpenGL.GL import *
from OpenGL.GLU import *
from pygame.locals import *
import sys

class AugmentedRealityApp:
    def __init__(self):
        # Initialisation de la caméra
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            print("Erreur: Impossible d'ouvrir la caméra")
            sys.exit(1)
        
        # Configuration de la caméra
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        # Dimensions de l'écran
        self.screen_width = 1280
        self.screen_height = 720
        
        # Initialisation de Pygame et OpenGL
        self.init_pygame_opengl()
        
        # Initialisation du détecteur ArUco
        self.init_aruco()
        
        # Matrice de caméra pour la projection 3D
        self.camera_matrix = np.array([
            [640, 0, 320],
            [0, 640, 240],
            [0, 0, 1]
        ], dtype=np.float32)
        
        self.dist_coeffs = np.zeros((4, 1))
        
        self.running = True
        
    def init_pygame_opengl(self):
        """Initialise Pygame avec OpenGL"""
        pygame.init()
        
        # Configuration de l'affichage OpenGL
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
        
    def init_aruco(self):
        """Initialise le détecteur ArUco"""
        try:
            # Pour les versions récentes d'OpenCV
            self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
            self.aruco_params = cv2.aruco.DetectorParameters()
            self.detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)
            print("Détecteur ArUco initialisé (nouvelle méthode)")
        except AttributeError:
            try:
                # Pour les anciennes versions
                self.aruco_dict = cv2.aruco.Dictionary_get(cv2.aruco.DICT_6X6_250)
                self.aruco_params = cv2.aruco.DetectorParameters_create()
                self.detector = None
                print("Détecteur ArUco initialisé (ancienne méthode)")
            except Exception as e:
                print(f"Erreur lors de l'initialisation d'ArUco: {e}")
                sys.exit(1)
    
    def capture_frame(self):
        """Capture une frame de la caméra avec la bonne orientation"""
        ret, frame = self.cap.read()
        if ret:
            # IMPORTANT: Ne pas flip l'image pour garder l'orientation naturelle
            # La caméra est déjà dans le bon sens
            return frame
        return None
    
    def detect_markers(self, frame):
        """Détecte les marqueurs ArUco dans l'image"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        if self.detector is not None:
            # Nouvelle méthode
            corners, ids, _ = self.detector.detectMarkers(gray)
        else:
            # Ancienne méthode
            corners, ids, _ = cv2.aruco.detectMarkers(
                gray, self.aruco_dict, parameters=self.aruco_params
            )
        
        return corners, ids
    
    def draw_video_background(self, frame):
        """Dessine la vidéo en arrière-plan avec la bonne orientation"""
        # Convertir l'image OpenCV pour Pygame
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Redimensionner si nécessaire
        if frame_rgb.shape[1] != self.screen_width or frame_rgb.shape[0] != self.screen_height:
            frame_rgb = cv2.resize(frame_rgb, (self.screen_width, self.screen_height))
        
        # Convertir en surface Pygame (pas de rotation pour garder l'orientation correcte)
        frame_surface = pygame.surfarray.make_surface(frame_rgb.swapaxes(0, 1))
        
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
        
        # Créer et appliquer la texture
        texture_data = pygame.image.tostring(frame_surface, "RGB", 1)
        
        texture_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, texture_id)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, self.screen_width, self.screen_height, 
                     0, GL_RGB, GL_UNSIGNED_BYTE, texture_data)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        
        glEnable(GL_TEXTURE_2D)
        
        # Dessiner un quad avec la texture
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
    
    def draw_3d_object(self, tvec, rvec, object_type=0):
        """Dessine un objet 3D à la position du marqueur"""
        glPushMatrix()
        
        # Convertir les vecteurs en matrice de rotation
        rmat, _ = cv2.Rodrigues(rvec)
        
        # Créer la matrice de transformation
        transform = np.eye(4)
        transform[:3, :3] = rmat
        # Ajuster l'échelle et la position
        transform[:3, 3] = tvec * 15
        
        # Appliquer la transformation
        glMultMatrixf(transform.T.flatten())
        
        # Dessiner l'objet selon le type
        if object_type == 0:  # Cube
            self.draw_cube()
        elif object_type == 1:  # Sphère
            self.draw_sphere()
        elif object_type == 2:  # Pyramide
            self.draw_pyramid()
        elif object_type == 3:  # Tétraèdre
            self.draw_tetrahedron()
        
        glPopMatrix()
    
    def draw_cube(self):
        """Dessine un cube coloré"""
        vertices = [
            (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, -1),
            (1, -1, 1), (1, 1, 1), (-1, -1, 1), (-1, 1, 1)
        ]
        
        faces = [
            (0, 1, 2, 3),  # Face avant
            (4, 5, 6, 7),  # Face arrière
            (1, 5, 7, 2),  # Face droite
            (0, 3, 6, 4),  # Face gauche
            (3, 2, 7, 6),  # Face haut
            (0, 4, 5, 1)   # Face bas
        ]
        
        colors = [
            (1, 0, 0), (0, 1, 0), (0, 0, 1),
            (1, 1, 0), (1, 0, 1), (0, 1, 1)
        ]
        
        # Dessiner les faces
        glBegin(GL_QUADS)
        for i, face in enumerate(faces):
            glColor3fv(colors[i])
            for vertex in face:
                glVertex3fv(vertices[vertex])
        glEnd()
        
        # Dessiner les arêtes en noir
        glColor3f(0, 0, 0)
        glLineWidth(2)
        glBegin(GL_LINES)
        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 7), (7, 6), (6, 4),
            (0, 4), (1, 5), (2, 7), (3, 6)
        ]
        for edge in edges:
            for vertex in edge:
                glVertex3fv(vertices[vertex])
        glEnd()
    
    def draw_sphere(self):
        """Dessine une sphère"""
        glColor3f(0, 0, 1)  # Bleu
        quadric = gluNewQuadric()
        gluSphere(quadric, 0.7, 32, 16)
        gluDeleteQuadric(quadric)
    
    def draw_pyramid(self):
        """Dessine une pyramide"""
        vertices = [
            (0, 1, 0),      # Sommet
            (1, -1, 1),      # Base avant droit
            (-1, -1, 1),     # Base avant gauche
            (-1, -1, -1),    # Base arrière gauche
            (1, -1, -1)      # Base arrière droit
        ]
        
        # Faces triangulaires
        faces = [
            (0, 1, 2),  # Face avant
            (0, 2, 3),  # Face gauche
            (0, 3, 4),  # Face arrière
            (0, 4, 1)   # Face droite
        ]
        
        colors = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0)]
        
        glBegin(GL_TRIANGLES)
        for i, face in enumerate(faces):
            glColor3fv(colors[i])
            for vertex in face:
                glVertex3fv(vertices[vertex])
        glEnd()
        
        # Base de la pyramide
        glColor3f(0.5, 0.5, 0.5)
        glBegin(GL_QUADS)
        for vertex in [1, 2, 3, 4]:
            glVertex3fv(vertices[vertex])
        glEnd()
    
    def draw_tetrahedron(self):
        """Dessine un tétraèdre"""
        vertices = [
            (0, 1, 0),
            (0.94, -0.33, 0.54),
            (-0.47, -0.33, 0.94),
            (-0.47, -0.33, -0.94)
        ]
        
        faces = [(0, 1, 2), (0, 2, 3), (0, 3, 1), (1, 3, 2)]
        colors = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0)]
        
        glBegin(GL_TRIANGLES)
        for i, face in enumerate(faces):
            glColor3fv(colors[i])
            for vertex in face:
                glVertex3fv(vertices[vertex])
        glEnd()
    
    def render_scene(self, frame, corners, ids):
        """Rend la scène AR complète"""
        # Dessiner le fond vidéo en premier
        self.draw_video_background(frame)
        
        # Puis dessiner les objets 3D par-dessus
        if ids is not None and len(ids) > 0:
            for i in range(len(ids)):
                # Estimer la pose du marqueur
                rvec, tvec, _ = cv2.aruco.estimatePoseSingleMarkers(
                    corners[i], 0.05, self.camera_matrix, self.dist_coeffs
                )
                
                # Dessiner un objet différent selon l'ID du marqueur
                object_type = ids[i][0] % 4
                self.draw_3d_object(tvec[0][0], rvec[0][0], object_type)
    
    def run(self):
        """Boucle principale de l'application"""
        clock = pygame.time.Clock()
        
        print("Application AR démarrée!")
        print("Placez des marqueurs ArUco devant la caméra")
        print("Appuyez sur ÉCHAP pour quitter")
        
        while self.running:
            # Gestion des événements
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
            
            # Effacer l'écran
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
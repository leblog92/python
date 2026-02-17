import numpy as np
from OpenGL.GL import *
from OpenGL.GLU import *
import cv2

class ARRenderer:
    def __init__(self):
        # Matrice de caméra (à ajuster selon votre webcam)
        self.camera_matrix = np.array([
            [640, 0, 320],
            [0, 640, 240],
            [0, 0, 1]
        ], dtype=np.float32)
        
        # Coefficients de distortion
        self.dist_coeffs = np.zeros((4, 1))
        
        # Liste des positions des marqueurs
        self.marker_positions = []
        
        # Couleurs pour les différents objets
        self.colors = [
            (1, 0, 0), (0, 1, 0), (0, 0, 1),
            (1, 1, 0), (1, 0, 1), (0, 1, 1)
        ]
    
    def draw_cube(self):
        """Dessine un cube 3D"""
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
        
        # Dessiner les faces
        glBegin(GL_QUADS)
        for i, face in enumerate(faces):
            glColor3fv(self.colors[i % len(self.colors)])
            for vertex in face:
                glVertex3fv(vertices[vertex])
        glEnd()
        
        # Dessiner les arêtes
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
        """Dessine une sphère 3D"""
        quadric = gluNewQuadric()
        gluQuadricDrawStyle(quadric, GLU_FILL)
        gluSphere(quadric, 0.5, 32, 16)
        gluDeleteQuadric(quadric)
    
    def draw_pyramid(self):
        """Dessine une pyramide 3D"""
        vertices = [
            (0, 1, 0),  # Sommet
            (1, -1, 1), (-1, -1, 1), (-1, -1, -1), (1, -1, -1)  # Base
        ]
        
        faces = [
            (0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1),  # Faces triangulaires
            (1, 2, 3, 4)  # Base
        ]
        
        glBegin(GL_TRIANGLES)
        for i, face in enumerate(faces[:4]):
            glColor3fv(self.colors[i % len(self.colors)])
            for vertex in face:
                glVertex3fv(vertices[vertex])
        glEnd()
        
        glBegin(GL_QUADS)
        glColor3fv(self.colors[4])
        for vertex in faces[4]:
            glVertex3fv(vertices[vertex])
        glEnd()
    
    def render_all_objects(self):
        """Rend tous les objets 3D aux positions des marqueurs"""
        for i, (tvec, rvec) in enumerate(self.marker_positions):
            glPushMatrix()
            
            # Convertir les vecteurs en matrice de transformation
            rmat, _ = cv2.Rodrigues(rvec)
            
            # Créer la matrice de transformation 4x4
            transform = np.eye(4)
            transform[:3, :3] = rmat
            transform[:3, 3] = tvec * 15  # Échelle ajustée
            
            # Appliquer la transformation
            glMultMatrixf(transform.T.flatten())
            
            # Dessiner un objet différent selon l'index
            object_type = i % 3
            if object_type == 0:
                self.draw_cube()
            elif object_type == 1:
                self.draw_sphere()
            else:
                self.draw_pyramid()
            
            glPopMatrix()
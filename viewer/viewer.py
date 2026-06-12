#!/usr/bin/env python3
"""
Visionneuse d'images (JPG/PNG) affichant simultanement la metadonnee "Commentaires".

Dependances :
    pip install Pillow

Utilisation :
    python visionneuse_images.py [dossier]

Si aucun dossier n'est passe en argument, un selecteur s'ouvre.

Navigation :
    Fleche gauche / droite  : image precedente / suivante
    Molette                 : precedente / suivante
    Ctrl+O                  : ouvrir un autre dossier
    Echap                   : quitter
"""

import os
import sys
import tkinter as tk
from tkinter import filedialog, ttk

from PIL import Image, ImageTk
from PIL.ExifTags import TAGS

EXTENSIONS = (".jpg", ".jpeg", ".png")


def lire_commentaires(chemin):
    """Extrait le commentaire/description de l'image, quel que soit le format."""
    try:
        with Image.open(chemin) as img:
            # --- PNG : commentaires stockes dans img.info (tEXt/iTXt) ---
            if img.format == "PNG":
                for cle in ("Comment", "Comments", "Description", "comment", "Commentaires"):
                    if cle in img.info and img.info[cle]:
                        return str(img.info[cle])

            # --- JPEG : EXIF ---
            exif = img.getexif()
            if exif:
                # Niveau principal (IFD0) : XPComment, ImageDescription...
                valeurs = {}
                for tag_id, valeur in exif.items():
                    nom = TAGS.get(tag_id, tag_id)
                    valeurs[nom] = valeur

                # Sous-IFD EXIF (0x8769) : c'est la que se trouve UserComment (37510)
                try:
                    sous = exif.get_ifd(0x8769)
                    for tag_id, valeur in sous.items():
                        nom = TAGS.get(tag_id, tag_id)
                        valeurs.setdefault(nom, valeur)
                except Exception:
                    pass

                for cle in ("XPComment", "UserComment", "ImageDescription"):
                    if cle in valeurs and valeurs[cle]:
                        v = valeurs[cle]
                        # XPComment est souvent encode en UTF-16LE (bytes ou tuple)
                        if cle == "XPComment":
                            v = decoder_xp(v)
                        elif isinstance(v, bytes):
                            v = decoder_user_comment(v)
                        if v and str(v).strip():
                            return str(v).strip()

            # --- Repli : champ generique dans img.info ---
            for cle in ("comment", "Comment", "Description", "parameters"):
                if cle in img.info and img.info[cle]:
                    return str(img.info[cle])

            # --- Dernier repli : segment COM brut du JPEG (commentaire JFIF) ---
            com = lire_segment_com(chemin)
            if com:
                return com
    except Exception as e:
        return f"(Erreur de lecture : {e})"
    return "(Aucun commentaire)"


def lire_segment_com(chemin):
    """Lit le segment COM (0xFFFE) brut d'un fichier JPEG, si present."""
    try:
        with open(chemin, "rb") as f:
            donnees = f.read()
        if donnees[:2] != b"\xff\xd8":  # pas un JPEG
            return None
        i = 2
        while i < len(donnees) - 1:
            if donnees[i] != 0xFF:
                i += 1
                continue
            marqueur = donnees[i + 1]
            if marqueur == 0xDA:  # debut des donnees image : on arrete
                break
            if marqueur in (0xD8, 0xD9) or 0xD0 <= marqueur <= 0xD7:
                i += 2
                continue
            longueur = int.from_bytes(donnees[i + 2:i + 4], "big")
            if marqueur == 0xFE:  # segment COM
                contenu = donnees[i + 4:i + 2 + longueur]
                for enc in ("utf-8", "utf-16-le", "latin-1"):
                    try:
                        txt = contenu.decode(enc).strip("\x00").strip()
                        if txt:
                            return txt
                    except Exception:
                        pass
            i += 2 + longueur
    except Exception:
        pass
    return None


def decoder_xp(valeur):
    """Decode un champ XP* Windows (UTF-16LE)."""
    try:
        if isinstance(valeur, (tuple, list)):
            valeur = bytes(valeur)
        if isinstance(valeur, bytes):
            return valeur.decode("utf-16-le", errors="ignore").rstrip("\x00")
    except Exception:
        pass
    return str(valeur)


def decoder_user_comment(valeur):
    """Decode un EXIF UserComment (prefixe d'encodage de 8 octets)."""
    try:
        if valeur[:8] == b"UNICODE\x00":
            return valeur[8:].decode("utf-16-be", errors="ignore").rstrip("\x00")
        if valeur[:8] == b"ASCII\x00\x00\x00":
            return valeur[8:].decode("ascii", errors="ignore").rstrip("\x00")
        return valeur.decode("utf-8", errors="ignore").lstrip("\x00").strip()
    except Exception:
        return str(valeur)


class Visionneuse(tk.Tk):
    def __init__(self, dossier=None):
        super().__init__()
        self.title("Visionneuse d'images — Commentaires")
        self.geometry("1000x720")
        self.configure(bg="#1e1e1e")

        self.images = []
        self.index = 0
        self.photo = None
        self._dernier_index_affiche = None  # evite de recharger inutilement

        # ===== Disposition principale : gauche (image) / droite (commentaire) =====
        principal = tk.Frame(self, bg="#1e1e1e")
        principal.pack(fill="both", expand=True)

        # --- Colonne gauche : image + nom + navigation ---
        gauche = tk.Frame(principal, bg="#1e1e1e")
        gauche.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Label(gauche, bg="#1e1e1e")
        self.canvas.pack(fill="both", expand=True, padx=10, pady=(10, 4))

        self.lbl_fichier = tk.Label(gauche, text="", bg="#1e1e1e", fg="#9cdcfe",
                                     font=("Segoe UI", 10, "bold"), wraplength=600)
        self.lbl_fichier.pack(fill="x", padx=10)

        barre = tk.Frame(gauche, bg="#1e1e1e")
        barre.pack(fill="x", padx=10, pady=(4, 8))
        tk.Button(barre, text="◀ Precedente", command=self.precedente).pack(side="left")
        tk.Button(barre, text="Suivante ▶", command=self.suivante).pack(side="left", padx=6)
        tk.Button(barre, text="📁 Ouvrir un dossier", command=self.choisir_dossier).pack(side="right")
        self.lbl_compteur = tk.Label(barre, text="", bg="#1e1e1e", fg="#808080")
        self.lbl_compteur.pack(side="right", padx=12)

        # --- Colonne droite : commentaire avec ascenseur ---
        droite = tk.LabelFrame(principal, text="Commentaires", bg="#252526",
                               fg="#dcdcaa", font=("Segoe UI", 10, "bold"))
        droite.pack(side="right", fill="both", padx=(0, 10), pady=10)
        droite.configure(width=360)
        droite.pack_propagate(False)  # garde la largeur fixe

        conteneur_txt = tk.Frame(droite, bg="#252526")
        conteneur_txt.pack(fill="both", expand=True, padx=6, pady=6)

        ascenseur = tk.Scrollbar(conteneur_txt)
        ascenseur.pack(side="right", fill="y")

        self.txt_commentaire = tk.Text(conteneur_txt, wrap="word",
                                       bg="#252526", fg="#d4d4d4",
                                       font=("Segoe UI", 11), relief="flat",
                                       yscrollcommand=ascenseur.set)
        self.txt_commentaire.pack(side="left", fill="both", expand=True)
        ascenseur.config(command=self.txt_commentaire.yview)
        self.txt_commentaire.configure(state="disabled")

        # Raccourcis
        self.bind("<Left>", lambda e: self.precedente())
        self.bind("<Right>", lambda e: self.suivante())
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Control-o>", lambda e: self.choisir_dossier())
        self.bind("<MouseWheel>", self.molette)        # Windows / macOS
        self.bind("<Button-4>", lambda e: self.precedente())  # Linux
        self.bind("<Button-5>", lambda e: self.suivante())    # Linux
        # Redimensionnement differe : on ne reajuste l'image qu'apres
        # que la fenetre se soit stabilisee (evite l'effet d'agrandissement).
        self._resize_job = None
        self.canvas.bind("<Configure>", self._sur_redimension)

        if dossier:
            self.charger_dossier(dossier)
        else:
            self.after(100, self.choisir_dossier)

    def molette(self, event):
        if event.delta > 0:
            self.precedente()
        else:
            self.suivante()

    def _sur_redimension(self, event):
        """Redimensionnement differe : ne rejoue le rendu qu'une fois stabilise."""
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(120, self.ajuster_image)

    def choisir_dossier(self):
        dossier = filedialog.askdirectory(title="Choisir un dossier d'images")
        if dossier:
            self.charger_dossier(dossier)

    def charger_dossier(self, dossier):
        try:
            fichiers = sorted(
                os.path.join(dossier, f)
                for f in os.listdir(dossier)
                if f.lower().endswith(EXTENSIONS)
            )
        except OSError as e:
            self.lbl_fichier.config(text=f"Erreur : {e}")
            return

        if not fichiers:
            self.images = []
            self.lbl_fichier.config(text="Aucune image JPG/PNG dans ce dossier.")
            self.canvas.config(image="")
            self.maj_commentaire("")
            self.lbl_compteur.config(text="")
            return

        self.images = fichiers
        self.index = 0
        self.afficher()

    def precedente(self):
        if self.images:
            self.index = (self.index - 1) % len(self.images)
            self.afficher()

    def suivante(self):
        if self.images:
            self.index = (self.index + 1) % len(self.images)
            self.afficher()

    def afficher(self):
        """Affiche l'image courante : met a jour image, nom, compteur, commentaire."""
        if not self.images:
            return
        chemin = self.images[self.index]
        self.lbl_fichier.config(text=os.path.basename(chemin))
        self.lbl_compteur.config(text=f"{self.index + 1} / {len(self.images)}")
        self.maj_commentaire(lire_commentaires(chemin))
        self.ajuster_image()

    def ajuster_image(self):
        """(Re)calcule l'affichage de l'image courante a la taille du canvas."""
        self._resize_job = None
        if not self.images:
            return
        chemin = self.images[self.index]
        try:
            img = Image.open(chemin)
            img = img.convert("RGBA") if img.mode in ("P", "LA") else img.convert("RGB")

            zone_l = max(self.canvas.winfo_width(), 100)
            zone_h = max(self.canvas.winfo_height(), 100)
            copie = img.copy()
            copie.thumbnail((zone_l, zone_h), Image.LANCZOS)

            self.photo = ImageTk.PhotoImage(copie)
            self.canvas.config(image=self.photo)
        except Exception as e:
            self.canvas.config(image="")
            self.lbl_fichier.config(text=f"Impossible d'afficher : {e}")

    def maj_commentaire(self, texte):
        self.txt_commentaire.configure(state="normal")
        self.txt_commentaire.delete("1.0", "end")
        self.txt_commentaire.insert("1.0", texte)
        self.txt_commentaire.configure(state="disabled")


if __name__ == "__main__":
    dossier_initial = sys.argv[1] if len(sys.argv) > 1 else None
    Visionneuse(dossier_initial).mainloop()
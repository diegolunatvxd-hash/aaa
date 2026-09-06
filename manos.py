import ctypes
import time
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# ==============================================================================
# CONFIGURACIÓN DE PANTALLA Y UTILIDADES
# ==============================================================================
try:
    user32 = ctypes.windll.user32
    SCREEN_W, SCREEN_H = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
except Exception:
    SCREEN_W, SCREEN_H = 1920, 1080

WINDOW_NAME = 'Motor de Efectos Nodal Pro'
cv2.namedWindow(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN)
cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

HAND_CONNECTIONS = [(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),(17,18),(18,19),(19,20),(0,17)]

# ==============================================================================
# CLASES DEL EDITOR GRÁFICO (UI INTERNA)
# ==============================================================================
class Node:
    def __init__(self, type_name, x, y):
        self.type_name = type_name
        self.x = x
        self.y = y
        self.w = 180 if type_name != 'Pixelear' else 210
        self.child = None  
        self.value = 15 # Usado para configurar el tamaño del pixel u otros

    @property
    def h(self): 
        return 75 if self.type_name == 'Pixelear' else 60

    def get_in_sock(self):
        if self.type_name == 'Figura': return None
        return (self.x, self.y + 30)

    def get_out_sock(self):
        return (self.x + self.w, self.y + 30)

    def draw(self, canvas):
        color_head = (100, 50, 50) if self.type_name == 'Figura' else (50, 100, 50)
        cv2.rectangle(canvas, (self.x, self.y), (self.x + self.w, self.y + self.h), (30, 30, 30), -1)
        cv2.rectangle(canvas, (self.x, self.y), (self.x + self.w, self.y + 25), color_head, -1)
        cv2.rectangle(canvas, (self.x, self.y), (self.x + self.w, self.y + self.h), (150, 150, 150), 1)
        
        cv2.putText(canvas, self.type_name, (self.x + 10, self.y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)

        # UI específica para Pixelear
        if self.type_name == 'Pixelear':
            # Botón [-]
            cv2.rectangle(canvas, (self.x + 10, self.y + 35), (self.x + 40, self.y + 60), (50, 50, 150), -1)
            cv2.putText(canvas, "-", (self.x + 20, self.y + 53), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
            # Texto
            cv2.putText(canvas, f"Tam: {self.value}", (self.x + 55, self.y + 53), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,200,200), 1)
            # Botón [+]
            cv2.rectangle(canvas, (self.x + self.w - 40, self.y + 35), (self.x + self.w - 10, self.y + 60), (50, 150, 50), -1)
            cv2.putText(canvas, "+", (self.x + self.w - 30, self.y + 53), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)

        # Enchufes
        in_s = self.get_in_sock()
        if in_s: cv2.circle(canvas, in_s, 6, (0, 255, 0), -1)
        cv2.circle(canvas, self.get_out_sock(), 6, (0, 0, 255), -1)

class FigureNode(Node):
    def __init__(self, x, y):
        super().__init__('Figura', x, y)
        self.w = 240
        self.vertices = [[0, 8]] # Comienza con 1 vértice por defecto

    @property
    def h(self): return 35 + len(self.vertices) * 30 + 35

    def draw(self, canvas):
        super().draw(canvas)
        cy = self.y + 35
        for i, v in enumerate(self.vertices):
            # Botón Mano
            cv2.rectangle(canvas, (self.x + 10, cy), (self.x + 80, cy + 22), (70, 70, 70), -1)
            cv2.putText(canvas, f"Mano:{v[0]}", (self.x + 15, cy + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)
            
            # Botón Punto (Activa Lista)
            cv2.rectangle(canvas, (self.x + 90, cy), (self.x + 170, cy + 22), (90, 70, 30), -1)
            cv2.putText(canvas, f"Pto: {v[1]:02d} v", (self.x + 95, cy + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)
            
            # Botón Borrar (X)
            cv2.rectangle(canvas, (self.x + 180, cy), (self.x + 205, cy + 22), (50, 50, 150), -1)
            cv2.putText(canvas, "X", (self.x + 187, cy + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)
            cy += 30

        # Botón Añadir Vértice
        cv2.rectangle(canvas, (self.x + 10, cy), (self.x + self.w - 10, cy + 25), (50, 150, 50), -1)
        cv2.putText(canvas, "+ Anadir Vertice", (self.x + 55, cy + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)


# Variables Globales del Editor
nodes = [FigureNode(100, 150)]
dragging_node = None
drag_off = (0,0)
connecting_from = None
mouse_pos = (0,0)
dropdown_active = None # Guardará un dict: {'node': fig_node, 'v_idx': index_vertice, 'x': x, 'y': y}

toolbar = [
    "Figura", "Invertir", "Pixelear", "Hue", "Map", 
    "Particulas", "Sepia", "B/N", "Bordes", "Desenfoque", "Umbral"
]

# ==============================================================================
# INTERACCIÓN CON RATÓN Y MENÚ DESPLEGABLE
# ==============================================================================
def draw_dropdown(canvas):
    if not dropdown_active: return
    dx, dy = dropdown_active['x'], dropdown_active['y']
    # Dibujar panel 5 columnas x 5 filas (para los 21 puntos)
    cv2.rectangle(canvas, (dx, dy), (dx + 160, dy + 135), (20, 20, 20), -1)
    cv2.rectangle(canvas, (dx, dy), (dx + 160, dy + 135), (200, 200, 200), 1)
    for i in range(21):
        row, col = i // 5, i % 5
        bx, by = dx + 5 + col * 30, dy + 5 + row * 25
        cv2.rectangle(canvas, (bx, by), (bx + 28, by + 23), (70, 70, 70), -1)
        cv2.putText(canvas, str(i), (bx + 3 + (5 if i<10 else 0), by + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)

def mouse_callback(event, x, y, flags, param):
    global dragging_node, drag_off, connecting_from, mouse_pos, nodes, dropdown_active
    mouse_pos = (x, y)

    if event == cv2.EVENT_LBUTTONDOWN:
        # 1. Comprobar Lista Desplegable (Dropdown)
        if dropdown_active:
            dx, dy = dropdown_active['x'], dropdown_active['y']
            if dx <= x <= dx + 160 and dy <= y <= dy + 135:
                # Calcular qué número hizo clic
                rx, ry = x - dx - 5, y - dy - 5
                col, row = rx // 30, ry // 25
                if 0 <= col < 5 and 0 <= row < 5:
                    idx = row * 5 + col
                    if idx <= 20:
                        dropdown_active['node'].vertices[dropdown_active['v_idx']][1] = idx
            dropdown_active = None # Cerrar dropdown si se hace clic dentro o fuera
            return
        
        # 2. Comprobar clic en Barra de Herramientas
        btn_w = SCREEN_W // len(toolbar)
        if y < 40:
            idx = x // btn_w
            if idx < len(toolbar):
                t_name = toolbar[idx]
                if t_name == 'Figura': nodes.append(FigureNode(50, 60))
                else: nodes.append(Node(t_name, 50, 60))
            return

        # 3. Iniciar conexión desde enchufe de salida
        for n in nodes:
            ox, oy = n.get_out_sock()
            if (x-ox)**2 + (y-oy)**2 < 100:
                connecting_from = n
                return

        # 4. Interacción UI de los Nodos (Botones internos)
        for n in nodes:
            if isinstance(n, FigureNode):
                cy = n.y + 35
                for i in range(len(n.vertices)):
                    if cy <= y <= cy+22:
                        if n.x+10 <= x <= n.x+80: 
                            n.vertices[i][0] = 1 - n.vertices[i][0] # Cambiar mano
                        elif n.x+90 <= x <= n.x+170: 
                            # Abrir lista desplegable debajo del botón
                            dropdown_active = {'node': n, 'v_idx': i, 'x': n.x+90, 'y': cy+25}
                        elif n.x+180 <= x <= n.x+205: 
                            if len(n.vertices) > 1: n.vertices.pop(i) # Borrar
                        return
                    cy += 30
                if n.x+10 <= x <= n.x+n.w-10 and cy <= y <= cy+25:
                    n.vertices.append([0, 0])
                    return
            elif n.type_name == 'Pixelear':
                if n.y+35 <= y <= n.y+60:
                    if n.x+10 <= x <= n.x+40: n.value = max(2, n.value - 2)
                    elif n.x+n.w-40 <= x <= n.x+n.w-10: n.value += 2
                    return

        # 5. Arrastrar nodo
        for n in reversed(nodes):
            if n.x <= x <= n.x+n.w and n.y <= y <= n.y+25:
                dragging_node = n
                drag_off = (x - n.x, y - n.y)
                return

    elif event == cv2.EVENT_RBUTTONDOWN:
        dropdown_active = None
        # Eliminar nodo (clic derecho en cabecera)
        for i, n in enumerate(nodes):
            if n.x <= x <= n.x+n.w and n.y <= y <= n.y+25:
                for parent in nodes:
                    if parent.child == n: parent.child = None
                nodes.pop(i)
                return

        # Desconectar enchufes
        for n in nodes:
            ox, oy = n.get_out_sock()
            if (x-ox)**2 + (y-oy)**2 < 100:
                n.child = None
                return
            ins = n.get_in_sock()
            if ins and (x-ins[0])**2 + (y-ins[1])**2 < 100:
                for parent in nodes:
                    if parent.child == n: parent.child = None
                return

    elif event == cv2.EVENT_MOUSEMOVE:
        if dragging_node:
            dragging_node.x = x - drag_off[0]
            dragging_node.y = y - drag_off[1]

    elif event == cv2.EVENT_LBUTTONUP:
        if connecting_from:
            for n in nodes:
                ins = n.get_in_sock()
                if ins and n != connecting_from and (x-ins[0])**2 + (y-ins[1])**2 < 200:
                    connecting_from.child = n
                    break
            connecting_from = None
        dragging_node = None

cv2.setMouseCallback(WINDOW_NAME, mouse_callback)


# ==============================================================================
# PIPELINE DE PROCESAMIENTO DE FORMAS Y EFECTOS
# ==============================================================================
def process_effects(image, pts, node_chain):
    if not pts: return
    img_h, img_w = image.shape[:2]

    # CALCULAR DELIMITADOR BASADO EN LA CANTIDAD DE PUNTOS
    if len(pts) == 1:
        # Modo 1 Vértice: Círculo alrededor del punto
        cx, cy = pts[0]
        r = 60
        bx, by, bw, bh = cx - r, cy - r, r*2, r*2
    elif len(pts) == 2:
        # Modo 2 Vértices: Cuadrado/Rectángulo alineado en sus esquinas
        bx, by = min(pts[0][0], pts[1][0]), min(pts[0][1], pts[1][1])
        bw, bh = abs(pts[0][0] - pts[1][0]), abs(pts[0][1] - pts[1][1])
    else:
        # Modo 3+ Vértices: Polígono libre
        pts_arr = np.array(pts, dtype=np.int32)
        bx, by, bw, bh = cv2.boundingRect(pts_arr)

    # Proteger desbordamiento en la pantalla
    x1, y1 = max(0, bx), max(0, by)
    x2, y2 = min(img_w, bx + bw), min(img_h, by + bh)
    if (x2 - x1) <= 1 or (y2 - y1) <= 1: return

    # CREAR LA MÁSCARA PERFECTA SEGÚN LA FORMA
    mask = np.zeros((y2 - y1, x2 - x1), dtype=np.uint8)
    if len(pts) == 1:
        cv2.circle(mask, (cx - x1, cy - y1), r, 255, -1)
    elif len(pts) == 2:
        mask.fill(255) # Las 4 esquinas abarcan todo el recorte ROI
    else:
        cv2.fillPoly(mask, [pts_arr - [x1, y1]], 255)

    roi = image[y1:y2, x1:x2].copy()

    # APLICAR LA CADENA DE EFECTOS AL ROI
    for node in node_chain:
        eff = node.type_name
        if eff == 'Invertir': 
            roi = cv2.bitwise_not(roi)
        elif eff == 'Pixelear':
            # INTER_NEAREST: Sin suavizado bilineal, conserva la dureza de 8 bits
            pixel_size = max(1, node.value)
            rh, rw = roi.shape[:2]
            small = cv2.resize(roi, (max(1, rw//pixel_size), max(1, rh//pixel_size)), interpolation=cv2.INTER_NEAREST)
            roi = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)
        elif eff == 'Hue':
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            hsv[:,:,0] = (hsv[:,:,0].astype(int) + 90) % 180
            roi = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        elif eff == 'Map':
            roi = cv2.applyColorMap(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), cv2.COLORMAP_JET)
        elif eff == 'B/N':
            roi = cv2.cvtColor(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        elif eff == 'Bordes':
            edges = cv2.Canny(roi, 100, 200)
            roi = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        elif eff == 'Desenfoque':
            roi = cv2.GaussianBlur(roi, (21, 21), 0)
        elif eff == 'Umbral':
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
            roi = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
        elif eff == 'Sepia':
            kernel = np.array([[0.272, 0.534, 0.131], [0.349, 0.686, 0.168], [0.393, 0.769, 0.189]])
            roi = cv2.transform(roi, kernel)
            roi = np.clip(roi, 0, 255).astype(np.uint8)

    # Fusionar con el lienzo mediante la máscara de forma
    bg = image[y1:y2, x1:x2]
    bg[mask == 255] = roi[mask == 255]


# ==============================================================================
# BUCLE PRINCIPAL
# ==============================================================================
options = vision.HandLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path='hand_landmarker.task'),
    running_mode=vision.RunningMode.VIDEO, num_hands=2,
    min_hand_detection_confidence=0.5, min_tracking_confidence=0.5
)
cap = cv2.VideoCapture(0)
show_editor = True
show_skeleton = True # Reactivado por defecto

with vision.HandLandmarker.create_from_options(options) as detector:
    while cap.isOpened():
        success, frame = cap.read()
        if not success: continue

        frame = cv2.flip(frame, 1)
        cam_h, cam_w = frame.shape[:2]
        
        # Letterboxing para no estirar la cámara
        scale = min(SCREEN_W / cam_w, SCREEN_H / cam_h)
        nw, nh = int(cam_w * scale), int(cam_h * scale)
        dx, dy = (SCREEN_W - nw) // 2, (SCREEN_H - nh) // 2
        canvas = np.zeros((SCREEN_H, SCREEN_W, 3), dtype=np.uint8)
        canvas[dy:dy+nh, dx:dx+nw] = cv2.resize(frame, (nw, nh))

        # Procesamiento MediaPipe
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        res = detector.detect_for_video(mp_img, int(time.time() * 1000))
        
        all_hands = []
        if res.hand_landmarks:
            for hl in res.hand_landmarks:
                all_hands.append([(int(lm.x * nw + dx), int(lm.y * nh + dy)) for lm in hl])

        # 1. EJECUCIÓN DE NODOS
        for n in nodes:
            if isinstance(n, FigureNode):
                pts = []
                for h_idx, p_idx in n.vertices:
                    if h_idx < len(all_hands): pts.append(all_hands[h_idx][p_idx])
                
                chain = []
                curr = n.child
                while curr:
                    chain.append(curr) # Pasamos el objeto nodo completo para leer sus valores
                    curr = curr.child
                
                process_effects(canvas, pts, chain)

        # 2. DIBUJAR ESQUELETO Y NUMERACIÓN (Tecla A)
        if show_skeleton:
            for hand_pts in all_hands:
                for start_idx, end_idx in HAND_CONNECTIONS:
                    cv2.line(canvas, hand_pts[start_idx], hand_pts[end_idx], (0, 255, 0), 2)
                for idx, pt in enumerate(hand_pts):
                    cv2.circle(canvas, pt, 4, (0, 0, 255), -1)
                    cv2.putText(canvas, str(idx), (pt[0]+5, pt[1]-3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,255), 1)

        # 3. DIBUJAR INTERFAZ DE USUARIO
        if show_editor:
            # Barra superior
            cv2.rectangle(canvas, (0,0), (SCREEN_W, 40), (20,20,20), -1)
            btn_w = SCREEN_W // len(toolbar)
            for i, label in enumerate(toolbar):
                cv2.rectangle(canvas, (i*btn_w, 0), ((i+1)*btn_w, 40), (40,40,40), 1)
                cv2.putText(canvas, "+ "+label, (i*btn_w + 10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,255,200), 1)

            # Cables
            for n in nodes:
                if n.child:
                    ins = n.child.get_in_sock()
                    if ins: cv2.line(canvas, n.get_out_sock(), ins, (0, 255, 255), 2)
            if connecting_from:
                cv2.line(canvas, connecting_from.get_out_sock(), mouse_pos, (255,255,255), 1)

            # Nodos
            for n in nodes: n.draw(canvas)
            
            # Lista desplegable (se dibuja al final para que quede encima de todo)
            draw_dropdown(canvas)

            # Letreros informativos
            cv2.putText(canvas, "A: Esqueleto | B: UI | Clic Izq: Modificar | Clic Der: Borrar/Desconectar", 
                        (10, SCREEN_H - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255), 1)

        cv2.imshow(WINDOW_NAME, canvas)
        
        # Teclado
        key = cv2.waitKey(5) & 0xFF
        if key == 27: break # ESC
        elif key == ord('a') or key == ord('A'): show_skeleton = not show_skeleton
        elif key == ord('b') or key == ord('B'): 
            show_editor = not show_editor
            dropdown_active = None

cap.release()
cv2.destroyAllWindows()
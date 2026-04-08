# Guía de Configuración de Equipos

## Modelos de router provistos

### Router Básico (modelo: completar con modelos reales)
- WiFi 2.4 GHz y 5 GHz
- 4 puertos LAN
- Acceso web: http://192.168.1.1
- Usuario admin por defecto: admin / admin

### Router WiFi 6 (modelos Hogar/Pro)
- WiFi 6 (802.11ax), bandas 2.4 y 5 GHz
- 4 puertos LAN Gigabit + 1 WAN
- Acceso web: http://192.168.0.1
- Usuario admin por defecto: admin (contraseña en sticker del equipo)

### Router Empresarial
- WiFi 6E, triple banda
- 4 LAN Gigabit + 2 WAN para balanceo de carga
- Acceso web: http://10.0.0.1
- Configuración inicial realizada por técnico

## Pasos para restablecer la conexión cuando no hay internet

1. **Verificar luces del router**:
   - Luz PWR: encendida fija (verde) ✓
   - Luz WAN/Internet: encendida fija (verde) = conexión OK
   - Luz WAN parpadeando = intento de conexión
   - Luz WAN apagada o roja = sin señal del proveedor

2. **Reinicio básico**:
   - Apagar el router (botón o desenchufar)
   - Esperar 30 segundos
   - Encender y aguardar 2 minutos

3. **Reinicio de fábrica** (último recurso, borra configuración WiFi):
   - Mantener presionado el botón RESET por 10 segundos
   - El router reinicia con configuración de fábrica
   - Reconectar con contraseña del sticker

4. **Verificar cable de fibra**:
   - Asegurarse de que el cable SC/APC (verde) está correctamente insertado en la ONT
   - No doblar el cable con radio menor a 3 cm
   - La ONT debe tener luz PON encendida (verde fija)

## Pasos para preparar una visita técnica

Antes de la llegada del técnico:
- Tener a mano el DNI del titular
- Asegurarse de que haya un adulto presente
- Despejar el área donde está instalada la ONT/router
- Tener acceso al tablero eléctrico por si es necesario
- Anotar los síntomas: desde cuándo falla, si hay luces distintas, si otros dispositivos tienen el mismo problema

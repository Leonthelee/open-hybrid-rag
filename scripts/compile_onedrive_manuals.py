import os
import sys

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

DEST_DIR = r"C:\Users\daniel.diaz\.gemini\antigravity\scratch\Soporte_DGA"
os.makedirs(DEST_DIR, exist_ok=True)

docs = {
    "01_DGA_Soporte_N2_Expedientes_BPM_Alfresco.md": """---
title: "01_DGA_Soporte_N2_Expedientes_BPM_Alfresco"
tipo: soporte-nivel-2
tags: [soporte-dga, bpm, alfresco, expedientes, instancias, cpa, snia]
fecha: 2026-10-14
autor: "Dpto. Soporte Tecnologico DGA"
---
# Soporte Nivel 2 DGA: Gestion de Expedientes, Instancias BPM y Alfresco

> **DGA Core Tools — by Daniel Diaz L. & AI Engine Antigravity**  
> *Manual Canónico de Operación Interna Nivel 2 y 3 • Fuente: REQUERIMIENTOS DE SOPORTE Y SOLUCIONES v2*

---

## 1. Eliminacion de Expedientes
Cuando se solicita la eliminacion de un expediente:
1. **Validacion Formal DARH:**
   - Quien toma el requerimiento debe solicitar formalmente por correo la aprobacion del funcionario/a responsable designado por el DARH (Validadora oficial: Elizabeth Tamayo / Jefatura DARH).
2. **Analisis Tecnico Previo:**
   - **Regla 1:** Si el expediente esta finalizado (con etapa resultado), **NO PROCEDE** su eliminacion; se debe comunicar a la Jefatura DARH.
   - **Regla 2:** Si el expediente es un tramite valido ingresado desde Oficina Virtual, procede informar a la Jefatura DARH.
3. **Flujo de Ejecucion:**
   - **Si esta pendiente (P-REG) y es el ultimo correlativo:**
     1. Utilizar la funcionalidad del CPA para la eliminacion.
     2. Eliminar la instancia activa desde la API REST (`http://snia.mop.gov.cl/bpmrest-ui/`).
     3. Eliminar los archivos en Alfresco relacionados con el expediente.
     4. Informar al solicitante, con copia al Agente de Expedientes Regional y al encargado DARH.
   - **Si el expediente NO es el ultimo correlativo:**
     1. Marcar el expediente como `ELI` (Eliminado) en `BD_EXP..expt_situacionactualsolic`.
     2. Eliminar la instancia activa desde la API REST.
     3. Eliminar los archivos en Alfresco asociados.
     4. Informar con copia al Agente Regional y encargado DARH.

---

## 2. Eliminacion de Instancias en IBM BPM
- **Condicion:** Solo procede si es una actividad de ingreso sin codigo de expediente creado, o si es una instancia duplicada (ej: recursos de reconsideracion con pop-ups bloqueados), o expedientes reabiertos con instancia antigua en estado "terminada".
- **Procedimiento API REST:**
  1. Acceder a: `http://snia.mop.gov.cl/bpmrest-ui/`
  2. Autenticarse con credenciales de administracion (`admbpmps` o `admbpmpc`).
  3. **Si la instancia esta activa:** Ejecutar en estricto orden secuencial:
     - `PUT /rest/bpm/wle/v1/process/{IdInstancia}?action=suspend` (Suspender proceso) -> Esperar `200 OK`.
     - `PUT /rest/bpm/wle/v1/process/{IdInstancia}?action=terminate` (Terminar proceso) -> Esperar `200 OK`.
     - `DELETE /rest/bpm/wle/v1/process/{IdInstancia}?action=delete` (Suprimir proceso) -> Esperar `200 OK`.
  4. **Si la instancia ya esta "Terminada":** Solo ejecutar directamente `Suprimir proceso` (`DELETE ... action=delete`).

---

## 3. Eliminacion de Documentos en Alfresco
- **Validacion DARH Previa:**
  - Expedientes de Certificados: Validacion de Veronica Calderon.
  - Otros expedientes SNIA: Validacion de Elizabeth Tamayo.
- **Acceso y Eliminacion:**
  - URL del repositorio: `http://prod-wsp-alfresco:8080/share/page/`
  - Autenticacion: Credenciales ministeriales o usuario `admin`.
  - Ubicacion: Navegar a la carpeta asociada a la solicitud. Para certificados, ingresar al Sitio *"Proceso certificados"*.
  - Proceder con la eliminacion del archivo correspondiente.

---

## 4. Recuperacion de Instancias Perdidas
- **Sintoma:** La instancia existe a nivel de base de datos a nombre de un funcionario, pero no aparece en su bandeja de entrada de SNIA.
- **Solucion:**
  1. En `http://snia.mop.gov.cl/bpmrest-ui/`, ejecutar la llamada `Reanudar proceso` sobre la instancia (`action=resume`).
  2. Verificar en la bandeja del usuario mediante el **Process Admin Console** con usuario `admbpmps`.
  3. Si no se recupera, utilizar **Process Inspector** buscando por numero de instancia o codigo de expediente/solicitud.

---

## 5. Reasignacion de Actividades
1. En SNIA, ingresar con el usuario administrador regional (`dga.admsniaXX`).
2. Ir a menu *Reasignar Tarea*, filtrar expediente, seleccionar nuevo usuario destino y confirmar.
3. Si no aparece en SNIA:
   - Ir a **Process Admin Console**, login con `admbpmps`.
   - Navegar a *Help Process -> Reasignacion Tareas*.
   - Filtrar por ROL y Usuario, seleccionar la tarea y presionar *Reasignar Usuario*.
4. Si no aparece en Process Admin: Suspender y reiniciar el proceso en la API REST. Si aun no tiene objeto de negocio, derivar a Jose Rivas.
""",

    "02_DGA_Soporte_N2_SQL_Objetos_Negocio_Estados.md": """---
title: "02_DGA_Soporte_N2_SQL_Objetos_Negocio_Estados"
tipo: soporte-nivel-2
tags: [soporte-dga, bd_exp, sql-server, objetos-negocio, snia, oficina-virtual]
fecha: 2026-10-14
autor: "Dpto. Soporte Tecnologico DGA"
---
# Soporte Nivel 2 DGA: Objetos de Negocio y Estados de Expedientes

> **DGA Core Tools — by Daniel Diaz L. & AI Engine Antigravity**  
> *Manual Canónico de Operación Interna Nivel 2 y 3 • Fuente: REQUERIMIENTOS DE SOPORTE Y SOLUCIONES v2*

---

## 1. Generar Objeto de Negocio desde Oficina Virtual
Cuando un tramite entra por Oficina Virtual pero no genera su objeto de negocio en BPM:
1. **Paso 1: Obtener ID de Tramite:**
   - Ejecutar la consulta SQL de tramites sin objeto de negocio.
2. **Paso 2: Obtener Token de Autenticacion Swagger:**
   - Endpoint: `http://172.19.20.130:9080/auth-rest-portal/swagger-ui.html#!/authorization/generarTokenUsingPOST`
   - Payload POST:
   ```json
   {
     "apiCode": "AM006",
     "apiKey": "5PKBJ0LEHVYN7VW2UMP8CW38Z1FBNA",
     "app": "exponline"
   }
   ```
3. **Paso 3: Obtener Objeto de Negocio Bruto:**
   - Endpoint: `http://172.19.20.130:9080/dga-rest-portal/swagger-ui.html#!/tramites/getRequestBPMSniaByIdUsingGET`
   - (Endpoint soporte alternativo: `http://172.19.20.130:9080/dga-rest-portal-soporte/swagger-ui.html`)
   - Header: `Authorization: Bearer <TOKEN>`
   - Parametro: `Id: <ID_TRAMITE>`
4. **Paso 4: Limpieza de Objeto en Notepad++:**
   - Quitar comillas externas.
   - Reemplazar todos los caracteres de escape `\\`.
   - Reemplazar prefijos `ns2`, `ns3`, `ns4` por `mop`.
5. **Paso 5: Inyeccion SOAP mediante SoapUI:**
   - Endpoint SOAP: `http://prod-wsp-bpm02.moptt.gov.cl:9083/schema/`
   - Estructura Envelope:
   ```xml
   <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:inic="http://ND2/IniciarNDOnline.tws" xmlns:mop="http://MOPCND2" xmlns:sch="http://prod-wsp-bpm02.moptt.gov.cl:9083/schema/">
     <soapenv:Header/>
     <soapenv:Body>
       <inic:iniciarProceso>
         <!-- OBJETO DE NEGOCIO LIMPIO AQUI -->
       </inic:iniciarProceso>
     </soapenv:Body>
   </soapenv:Envelope>
   ```
   - Ejecutar la operacion `IniciarProceso`. Al recibir respuesta favorable, verificar en SNIA en la bandeja del Agente de Expediente.

---

## 2. Generar Objeto de Negocio desde Process Designer (SNIA)
1. Acceder a **Process Designer** con credenciales `Admbpmpc`.
2. Seleccionar el proceso correspondiente (`ND`, `VC`, `VPC`, etc.) y abrir en *Designer -> Main -> Process Inspector*.
3. Cambiar de *Process Center* a **Produccion** y buscar por codigo de expediente.
4. En el *Evaluador de Ejecucion*, escribir: `tw.local.expedienteND` (o variable del tipo de proceso) y presionar Ejecutar.
5. Copiar el XML del objeto de negocio obtenido e insertar en `BD_EXP`:
   ```sql
   INSERT INTO BD_EXP.dbo.Expt_ObjetoNegocioND 
     (ExpConcatLlave, IdInstancia, XMLNuevo, XMLAntiguo, FechaActualizacion)
   VALUES 
     ('CODIGO_EXPEDIENTE', NO_INSTANCIA, '<!-- XML NUEVO AQUI -->', '', GETDATE());
   ```

### Mapeo Canónico de Tablas de Objetos de Negocio:
| Prefijo Expediente | Tipo de Proceso | Tabla en BD_EXP |
| :--- | :--- | :--- |
| **ND** | Nuevos Derechos | `BD_EXP.dbo.Expt_ObjetoNegocioND` |
| **NR** | No Consuntivos / Regularizaciones | `BD_EXP.dbo.Expt_ObjetoNegocioNR` |
| **VC**, **VP** | Obras y Modificaciones | `BD_EXP.dbo.Expt_ObjetoNegocioObr` |
| **VPC**, **VF** | Traslados | `BD_EXP.dbo.Expt_ObjetoNegocioTrasl` |
| **FD**, **FO**, **DEN** | Fiscalizaciones y Denuncias | `BD_EXP.dbo.Expt_ObjetoNegocioFisc` |

---

## 3. Consulta y Cambio de Estado de Expediente en SQL Server
```sql
-- Consultar catalogo de tipos de expedientes
SELECT * FROM bd_par..part_tiposexpediente;

-- Buscar el ultimo correlativo de una serie
SELECT MAX(expcodigo) 
FROM bd_exp.dbo.expt_expediente 
WHERE texcodigo = 9 AND regcodigo = 8 AND procodigo = 3;

-- Consultar situacion actual del expediente
SELECT * 
FROM bd_exp..expt_situacionactualsolic
WHERE texcodigo = 5 AND regcodigo = 5 AND procodigo = 8 AND expcodigo = 137;

-- Modificar estado a Eliminado (ELI) o estados operativos (P-REG, A, D, etc.)
UPDATE bd_exp..expt_situacionactualsolic 
SET situacionactual = 'ELI'
WHERE texcodigo = 5 AND regcodigo = 5 AND procodigo = 8 AND expcodigo = 137;
```
""",

    "03_DGA_Soporte_N2_Procedimientos_Almacenados_y_Obras.md": """---
title: "03_DGA_Soporte_N2_Procedimientos_Almacenados_y_Obras"
tipo: soporte-nivel-2
tags: [soporte-dga, sql-server, stored-procedures, fiscalizacion, obras, extracciones]
fecha: 2026-10-14
autor: "Dpto. Soporte Tecnologico DGA"
---
# Soporte Nivel 2 DGA: Procedimientos Almacenados, Fiscalización y Obras

> **DGA Core Tools — by Daniel Diaz L. & AI Engine Antigravity**  
> *Manual Canónico de Operación Interna Nivel 2 y 3 • Fuente: REQUERIMIENTOS DE SOPORTE Y SOLUCIONES v2*

---

## 1. Eliminacion de Expedientes de Fiscalizacion (FD, FO, DEN)
La eliminacion de expedientes de fiscalizacion requiere 3 etapas estrictas:
1. **Eliminar Instancia BPM:** Consultar `IdInstancia` en `BD_EXP..Expt_ObjetoNegocioFisc` y suprimir en API REST.
2. **Eliminar Archivos Alfresco:** Suprimir nodo de expediente en `http://prod-wsp-alfresco:8080/share/page/`.
3. **Auditoria y Eliminacion en Base de Datos `BD_EXP`:**
   - **Paso A: Visualizacion Previa Obligatoria:** Antes de borrar, ejecutar el procedimiento de seleccion en Toad / SSMS:
     ```sql
     EXEC BD_EXP.dbo.MDAT_Seleccion_FD_DEN_FO 'DEN-0508-1', 33, 5, 8, 1;
     ```
     *Muestra: `UsuarioRolActividad`, `Expt_LOG_Mantencion` y `Expt_HistorialActividadesND`.*
   - **Paso B: Ejecucion del Procedimiento de Eliminacion:**
     ```sql
     EXEC BD_EXP.dbo.MDAT_Elimina_FD_DEN_FO @ExpConcatLLave, @TexCodigo, @RegCodigo, @ProCodigo, @ExpCodigo;
     ```
     *Parametros de `TexCodigo`: `FD = 23`, `FO = 32`, `DEN = 33`.*  
     Ejemplo para `FD-0101-1`:
     ```sql
     EXEC BD_EXP..MDAT_Elimina_FD_DEN_FO 'FD-0101-1', 23, 1, 1, 1;
     ```
   - **Paso C: Verificacion del Log de Auditoria:**
     ```sql
     SELECT * FROM BD_EXP.dbo.Expt_LOG_Mantencion WHERE ExpConcatLlave = 'DEN-0508-1';
     ```

---

## 2. Actualizacion de Coordenadas de Obras y Mediciones (Extracciones Efectivas)
Cuando se solicita cambio de coordenadas UTM para una obra (ej: `OB-1301-175`):
1. **Verificar Obra:**
   ```sql
   SELECT * FROM BD_CE2..CE2_OBRA_CAPTACION WHERE CODIGO = 'OB-1301-175';
   ```
2. **Actualizar Coordenadas en Informes de Medicion:**
   ```sql
   UPDATE BD_CE2_CONSULTA..CE2_INFORME_MEDICION
   SET UTM_NORTE = 6314182, UTM_ESTE = 338429, HUSO = 2
   WHERE CODIGO_OBRA = 'OB-1301-175';
   ```
3. **Calcular Ubicacion Hidrologica (Cuenca, Acuifero y Sector SHA):**
   Ejecutar el procedimiento geografico en `BD_SHP`:
   ```sql
   DECLARE @ret int, @st int, @desc varchar(200);
   EXEC @ret = [BD_SHP].[dbo].[SHP_getUbicacionesHidrologicas]
     @NATURALEZA = 1,
     @UTM_NORTE  = 6314182,
     @UTM_ESTE   = 338429,
     @HUSO       = 2,
     @status     = @st OUTPUT,
     @statusDesc = @desc OUTPUT;
   ```
   *Entrega: `COD_CUENCA`, `NOM_CUENCA`, `COD_ACUIFERO`, `NOM_ACUIFERO`, `SECTOR_SHA`.*
4. **Actualizar Datos Maestros de la Obra de Captacion:**
   ```sql
   UPDATE BD_CE2..CE2_OBRA_CAPTACION
   SET UTM_NORTE  = 6314182,
       UTM_ESTE   = 338429,
       HUSO       = 2,
       COD_CUENCA = 57,
       NOM_CUENCA = 'Rio Maipo',
       COD_ACUIFERO = 56,
       NOM_ACUIFERO = 'Maipo',
       SECTOR_SHA   = 'Colina Sur'
   WHERE CODIGO = 'OB-1301-175';
   ```

---

## 3. Cambio de Usuario de Derecho y Direccion
```sql
-- 1. Consultar derecho a modificar
SELECT * FROM BD_DCC..Dcct_DerechoUsuario
WHERE TexCodigo = 1 AND RegCodigo = 5 AND ProCodigo = 6
  AND ExpCodigo IN (800167, 800162, 800150, 800164);

-- 2. Consultar Rut y correlativo en catalogo de personas
SELECT Rut, PerCorrRut FROM BD_EXP..Expt_Personas WHERE Rut = '...';

-- 3. Actualizar titular del derecho
UPDATE BD_DCC..Dcct_DerechoUsuario
SET UsrRut = '000000000000000000-0',
    PerCorrRut = 450624
WHERE TexCodigo = 1 AND RegCodigo = 5 AND ProCodigo = 6
  AND ExpCodigo IN (800167, 800162, 800150, 800164);
```
""",

    "04_DGA_Soporte_N2_Creacion_Usuarios_CPA_SIGIRH_SQL.md": """---
title: "04_DGA_Soporte_N2_Creacion_Usuarios_CPA_SIGIRH_SQL"
tipo: soporte-nivel-2
tags: [soporte-dga, cpa, sigirh, sql-server, pro-sqlwspclu, privilegios]
fecha: 2026-10-14
autor: "Dpto. Soporte Tecnologico DGA"
---
# Soporte Nivel 2 DGA: Alta de Usuarios CPA-SIGIRH y Credenciales SQL Server

> **DGA Core Tools — by Daniel Diaz L. & AI Engine Antigravity**  
> *Manual Canónico de Operación Interna Nivel 2 y 3 • Fuente: REQUERIMIENTOS DE SOPORTE Y SOLUCIONES v2*

---

## 1. Alta en CPA-SIGIRH
1. Acceder a **CPA-SIGIRH** con credenciales de administrador:
   - **Usuario:** `cpa_admin`
   - **Contraseña:** `sdit`
2. Ir a menu: *Mantención / Responsables -> Crear*.
3. Completar campos obligatorios: Rut, Nombre Completo, Unidad, Cargo, Profesion y Fecha de Ingreso, y Guardar.

---

## 2. Asignacion de Login y Privilegios en Base de Datos
1. **Actualizar Login en `BD_EXP`:**
   ```sql
   UPDATE BD_EXP..Expt_Responsable
   SET UsrLogin = 'vjara'
   WHERE ResRut = '0017010245-5';
   ```
   *Nota: Verificar previamente que el login no exista en la tabla.*
2. **Registrar Usuario en `BD_PRIVMOP`:**
   ```sql
   INSERT INTO BD_PRIVMOP..tbl_User 
     (fld_UserCode, fld_UserName, fld_UserPassword, fld_UserState, fld_MayDelete, fld_MayUpdate)
   VALUES 
     ('vjara', 'Victor Jara Jara', 'vjara', 'CR', 1, 1);
   ```
3. **Clonar Perfil de Privilegios Base:**
   ```sql
   INSERT INTO BD_PRIVMOP..tbl_UserProfile
   SELECT 'vjara', fld_ProfileName
   FROM BD_PRIVMOP..tbl_UserProfile
   WHERE fld_UserCode = 'ahernandez'
     AND fld_ProfileName NOT IN ('R_ELIMINAR_ETAPA', 'R_MOD_CADUCO', 'R_APPBNA');
   ```

---

## 3. Creacion de Login en Cluster SQL Server Produccion
1. Conectar por Escritorio Remoto al servidor: `172.16.71.41`.
2. Abrir **SQL Server Management Studio (SSMS)**.
3. Conectar a la instancia de cluster: `PRO-SQLWSPCLU`.
4. Ir a *Security -> New Login*:
   - Login Name: `vjara`
   - SQL Server Authentication: `vjara` (desmarcar Enforce password expiration temporalmente segun estandar).
5. En la seccion **User Mapping**, mapear el usuario asignando los roles `db_datareader` y `db_datawriter` sobre las **6 bases de datos institucionales**:
   - `BD_AUD` (Auditoría)
   - `BD_DCC` (Derechos Concedidos)
   - `BD_EXP` (Expedientes)
   - `BD_JUR` (Jurisprudencia)
   - `BD_PAR` (Parámetros)
   - `BD_PRIVMOP` (Privilegios)
   - `BD_TARIF` (Tarificación)
6. Probar inicio de sesion en CPA-SIGIRH con el usuario creado y validar navegación de menú sin errores de acceso.
""",

    "05_DGA_Soporte_Firma_Digital_Febos_OTP.md": """---
title: "05_DGA_Soporte_Firma_Digital_Febos_OTP"
tipo: soporte-nivel-2
tags: [soporte-dga, firma-digital, fea, febos, otp, google-authenticator, firmagob]
fecha: 2026-10-14
autor: "Dpto. Soporte Tecnologico DGA"
---
# Soporte Nivel 2 DGA: Firma Electrónica Avanzada (FEA), Febos y OTP

> **DGA Core Tools — by Daniel Diaz L. & AI Engine Antigravity**  
> *Manual Canónico de Operación Interna Nivel 2 y 3 • Fuente: Plataforma Febos y FirmaGob MINSEGPRES*

---

## 1. Firma Electrónica en Plataforma Febos
- **URL de Acceso:** Portal oficial de firma de documentos de la DGA.
- **Flujo Operativo:**
  1. El funcionario ingresa a Febos con sus credenciales institucionales.
  2. Selecciona la bandeja de documentos pendientes por firmar (Resoluciones, Decretos, Minutas, Ordinarios).
  3. Revisa la vista previa del documento.
  4. Presiona el boton **Firmar**.
  5. Se solicita el codigo de 6 digitos emitido por el segundo factor de autenticacion (**OTP / Token**).
  6. Una vez validado el OTP, el motor criptografico estampa la firma digital avanzada con validez legal Ley 19.799.

---

## 2. Configuracion de Componente OTP (Google Authenticator)
- **Componente para PC (Navegador Chrome):**
  1. Instalar la extension oficial de **Google Authenticator** en Google Chrome desde la Chrome Web Store.
  2. Abrir la extension, presionar el icono de lapiz / agregar cuenta y escanear el codigo QR provisto en la carta de entrega de FEA del funcionario.
  3. Si es ingreso manual: ingresar la clave secreta alfanumerica proporcionada por la SDIT.
  4. La extension generara codigos de 6 digitos que rotan cada 30 segundos.
- **Componente para Smartphone:**
  - Instalar **Google Authenticator** desde Google Play Store o Apple App Store y escanear el QR emitido por la entidad certificadora (E-Certchile / MINSEGPRES).

---

## 3. Renovacion de Certificado en FirmaGob (`https://firma.digital.gob.cl/`)
1. Ingresar a: `https://firma.digital.gob.cl/`
2. Seleccionar el boton **Acceso a FirmaGob**.
3. Autenticarse mediante **ClaveUnica** (RUT y ClaveUnica).
4. El portal desplegara el estado del certificado digital del funcionario:
   - Si esta proximo a vencer o vencido, pulsar **Renovar Certificado**.
   - Validar datos institucionales (Ministerio de Obras Publicas, Direccion General de Aguas, cargo y correo `@mop.gov.cl`).
5. Aceptar las condiciones del servicio y descargar el nuevo codigo QR para enrolar el OTP en Google Authenticator.
""",

    "06_DGA_Soporte_Sistemas_Legados_IETab_y_DameWare.md": """---
title: "06_DGA_Soporte_Sistemas_Legados_IETab_y_DameWare"
tipo: soporte-nivel-2
tags: [soporte-dga, ietab, dameware, soporte-remoto, snia-legado, activex, cpa]
fecha: 2026-10-14
autor: "Dpto. Soporte Tecnologico DGA"
---
# Soporte Nivel 2 DGA: Compatibilidad IE Tab y Asistencia Remota DameWare

> **DGA Core Tools — by Daniel Diaz L. & AI Engine Antigravity**  
> *Manual Canónico de Operación Interna Nivel 2 y 3 • Fuente: SDIT MOP & Soporte DGA*

---

## 1. Extension IE Tab para Sistemas Legados SNIA y CPA-BNA
- **Problema Tecnico:** Modulos historicos del SNIA, Catastro de Aguas y CPA requieren componentes ActiveX, applets de Java o motor Trident (Internet Explorer) que no son compatibles de forma nativa con Google Chrome ni Microsoft Edge moderno.
- **Solucion Oficial SDIT:**
  1. Instalar la extension **IE Tab** en Microsoft Edge o Google Chrome desde sus respectivas tiendas oficiales.
  2. Ejecutar el asistente de instalacion del componente binario auxiliar (`ietabhelper.exe`).
  3. Configurar la lista de URLs de emulacion automatica (*Auto URLs*):
     - `http://snia.mop.gov.cl/*`
     - `http://prod-wsp-cpa/*`
     - `http://172.16.*`
  4. Modo de emulacion de motor: Seleccionar **IE11 Standards Mode** o **IE8 Standards Mode** segun el requerimiento del modulo CPA.
  5. Con esta configuracion, al ingresar a las direcciones de SNIA, la pestaña se renderiza con el motor de Internet Explorer encapsulado dentro de Edge/Chrome.

---

## 2. Software de Control Remoto DameWare
- **Uso Oficial:** Asistencia tecnica remota asistida a funcionarios de la DGA a lo largo de todo Chile.
- **Instalacion y Verificacion:**
  1. Verificar si el equipo ya posee el agente en la bandeja del sistema (icono anaranjado en la barra de tareas de Windows). Si ya esta activo, no requiere accion.
  2. Si no esta instalado: Ejecutar el instalador corporativo `AGENTEDamewareRemote.exe`.
  3. Solicitar al funcionario su direccion IPv4 (obtenida mediante `cmd -> ipconfig`).
  4. Desde la consola DameWare Mini Remote Control del tecnico, ingresar la IP del equipo del usuario, autenticar con credenciales de dominio ministerial y solicitar autorizacion de pantalla remota.
"""
}

for filename, content in docs.items():
    filepath = os.path.join(DEST_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")
    print(f"✅ Generado manual canónico: {filename} ({len(content)} caracteres)")

print("\n🎉 Compilación de manuales de Soporte Nivel 2/3 completada.")

// Clase 4 - Estacion Meteorologica pura (sin LCD/botones)
// Sensores: DHT11 D2, LM35 A0, LDR A1 (con 10k a GND), Agua A2
// Actuador: Buzzer pasivo D6 (GND)
// Envia por Serial 9600: temp,hum,luz,agua  (CSV4 compatible Clase 3)
// Comandos: R=leer LM35 ahora, B=beep test, D=debug
#include <DHT.h>
#define DHT_PIN 2
#define DHT_TYPE DHT11
DHT dht(DHT_PIN, DHT_TYPE);

#define PIN_LM35 A0
#define PIN_LUZ  A1
#define PIN_AGUA A2
#define BUZZER_PIN 6
#define INTERVALO_MS 2000

typedef enum { TIPO_DIGITAL=0, TIPO_ANALOGICO=1 } TipoSensor;
typedef struct {
  char nombre[20];
  uint8_t pin;
  TipoSensor tipo;
  float valor;
  float umbral_alerta;
  float umbral_critico;
  bool activo;
  float offset;
} Sensor;

Sensor sensores[5];

void init_sensores(Sensor s[]) {
  strcpy(s[0].nombre, "DHT11_TEMP"); s[0].pin=2; s[0].tipo=TIPO_DIGITAL; s[0].valor=0; s[0].umbral_alerta=30; s[0].umbral_critico=35; s[0].activo=true; s[0].offset=0;
  strcpy(s[1].nombre, "DHT11_HUM");  s[1].pin=2; s[1].tipo=TIPO_DIGITAL; s[1].valor=0; s[1].umbral_alerta=80; s[1].umbral_critico=90; s[1].activo=true; s[1].offset=0;
  strcpy(s[2].nombre, "LM35");       s[2].pin=A0; s[2].tipo=TIPO_ANALOGICO; s[2].valor=0; s[2].umbral_alerta=30; s[2].umbral_critico=35; s[2].activo=true; s[2].offset=0.3;
  strcpy(s[3].nombre, "LDR");        s[3].pin=A1; s[3].tipo=TIPO_ANALOGICO; s[3].valor=0; s[3].umbral_alerta=600; s[3].umbral_critico=800; s[3].activo=true; s[3].offset=0;
  strcpy(s[4].nombre, "LLUVIA");     s[4].pin=A2; s[4].tipo=TIPO_ANALOGICO; s[4].valor=0; s[4].umbral_alerta=500; s[4].umbral_critico=800; s[4].activo=true; s[4].offset=0;
}

void leer_sensor(Sensor *s) {
  if (!s || !s->activo) return;
  if (s->tipo == TIPO_ANALOGICO) {
    int raw = analogRead(s->pin);
    if (strcmp(s->nombre, "LM35")==0) s->valor = (raw * 5.0 / 1023.0) * 100.0 + s->offset;
    else s->valor = raw;
  } else {
    if (strcmp(s->nombre, "DHT11_TEMP")==0) { float t=dht.readTemperature(); if(!isnan(t)) s->valor=t; }
    else if (strcmp(s->nombre, "DHT11_HUM")==0) { float h=dht.readHumidity(); if(!isnan(h)) s->valor=h; }
  }
}
void leer_todos(Sensor s[], int n){ for(int i=0;i<n;i++) if(s[i].activo) leer_sensor(&s[i]); }
Sensor* buscar_sensor(Sensor s[], int n, const char* nom){ for(int i=0;i<n;i++) if(strcmp(s[i].nombre,nom)==0) return &s[i]; return NULL; }

void actualizar_buzzer(Sensor s[], int n){
  Sensor *agua = buscar_sensor(s, n, "LLUVIA");
  Sensor *t = buscar_sensor(s, n, "DHT11_TEMP");
  bool debe = false;
  if(agua && agua->valor > 500) debe = true;
  if(t && t->valor > 35) debe = true;
  if(debe) tone(BUZZER_PIN, 2000); else noTone(BUZZER_PIN);
}

unsigned long ultima=0;

void setup(){
  Serial.begin(9600); dht.begin();
  pinMode(BUZZER_PIN, OUTPUT);
  init_sensores(sensores);
  Serial.println("ESTACION_METEO_CSV");
  tone(BUZZER_PIN, 1200); delay(120); noTone(BUZZER_PIN);
}
void loop(){
  if(Serial.available()){
    char c=Serial.read();
    if(c=='R'){ Sensor *p=buscar_sensor(sensores,5,"LM35"); if(p){ leer_sensor(p); Serial.print("AHORA "); Serial.print(p->nombre); Serial.print(","); Serial.println(p->valor,1);} }
    else if(c=='B'){ tone(BUZZER_PIN,2000); delay(200); noTone(BUZZER_PIN); Serial.println("BEEP OK"); }
    else if(c=='D'){ for(int i=0;i<5;i++){ Serial.print(i); Serial.print(" "); Serial.print(sensores[i].nombre); Serial.print(" "); Serial.print(sensores[i].valor,1); Serial.print(" pin"); Serial.println(sensores[i].pin); } }
  }
  if(millis()-ultima >= INTERVALO_MS){
    leer_todos(sensores,5);
    actualizar_buzzer(sensores,5);
    Sensor *t=buscar_sensor(sensores,5,"DHT11_TEMP");
    Sensor *h=buscar_sensor(sensores,5,"DHT11_HUM");
    Sensor *ldr=buscar_sensor(sensores,5,"LDR");
    Sensor *agua=buscar_sensor(sensores,5,"LLUVIA");
    if(t && h){
      Serial.print(t->valor,1); Serial.print(","); Serial.print(h->valor,0);
      Serial.print(","); Serial.print(ldr?ldr->valor:0,0);
      Serial.print(","); Serial.println(agua?agua->valor:0,0);
    }
    ultima=millis();
  }
}

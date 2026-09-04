// Clase 4 - Estacion Completa con Struct + Punteros + Actuadores + Speaker
// Cableado: DHT11 D2, LM35 A0, LDR A1 (con 10k a GND), Agua A2, LEDs D8/D9/D10 (220Ω a GND), Relay D7, Speaker + -> D6, Speaker - -> GND
// Envia por Serial 9600: temp,hum,luz,agua  (compatible Clase 3)
// Recibe: LED_ON/OFF, RELAY_ON/OFF
#include <DHT.h>
#define DHT_PIN 2
#define DHT_TYPE DHT11
DHT dht(DHT_PIN, DHT_TYPE);

#define PIN_LM35 A0
#define PIN_LUZ  A1
#define PIN_AGUA A2
#define LED_DIA 8
#define LED_TARDE 9
#define LED_NOCHE 10
#define RELAY_RIEGO 7
#define SPEAKER_PIN 6  // buzzer activo: + -> D6, - -> GND
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

Sensor sensores[6];

void init_sensores(Sensor s[]) {
  strcpy(s[0].nombre, "DHT11_TEMP"); s[0].pin=2; s[0].tipo=TIPO_DIGITAL; s[0].valor=0; s[0].umbral_alerta=30; s[0].umbral_critico=35; s[0].activo=true; s[0].offset=0;
  strcpy(s[1].nombre, "DHT11_HUM");  s[1].pin=2; s[1].tipo=TIPO_DIGITAL; s[1].valor=0; s[1].umbral_alerta=80; s[1].umbral_critico=90; s[1].activo=true; s[1].offset=0;
  strcpy(s[2].nombre, "LM35");       s[2].pin=A0; s[2].tipo=TIPO_ANALOGICO; s[2].valor=0; s[2].umbral_alerta=30; s[2].umbral_critico=35; s[2].activo=true; s[2].offset=0.3;
  strcpy(s[3].nombre, "LDR");        s[3].pin=A1; s[3].tipo=TIPO_ANALOGICO; s[3].valor=0; s[3].umbral_alerta=600; s[3].umbral_critico=800; s[3].activo=true; s[3].offset=0;
  strcpy(s[4].nombre, "LLUVIA");     s[4].pin=A2; s[4].tipo=TIPO_ANALOGICO; s[4].valor=0; s[4].umbral_alerta=500; s[4].umbral_critico=800; s[4].activo=true; s[4].offset=0;
  strcpy(s[5].nombre, "RTC");        s[5].pin=5; s[5].tipo=TIPO_DIGITAL; s[5].valor=0; s[5].umbral_alerta=0; s[5].umbral_critico=0; s[5].activo=false; s[5].offset=0;
}

void leer_sensor(Sensor *s) {
  if (!s->activo) return;
  if (s->tipo == TIPO_ANALOGICO) {
    int raw = analogRead(s->pin);
    if (strcmp(s->nombre, "LM35")==0) s->valor = (raw * 5.0 / 1023.0) * 100.0 + s->offset;
    else s->valor = raw;
  } else {
    if (strcmp(s->nombre, "DHT11_TEMP")==0) { float t=dht.readTemperature(); if(!isnan(t)) s->valor=t; }
    else if (strcmp(s->nombre, "DHT11_HUM")==0) { float h=dht.readHumidity(); if(!isnan(h)) s->valor=h; }
  }
}
void verificar_alertas(Sensor *s){
  if(!s->activo) return;
  if(strcmp(s->nombre,"LDR")==0){
    digitalWrite(LED_DIA, s->valor>600?HIGH:LOW);
    digitalWrite(LED_TARDE, (s->valor>=200 && s->valor<=600)?HIGH:LOW);
    digitalWrite(LED_NOCHE, s->valor<200?HIGH:LOW);
  }
}
void leer_todos(Sensor s[], int n){ for(int i=0;i<n;i++) if(s[i].activo) leer_sensor(&s[i]); }
void alertar_todos(Sensor s[], int n){ for(int i=0;i<n;i++) if(s[i].activo) verificar_alertas(&s[i]); }
Sensor* buscar_sensor(Sensor s[], int n, const char* nom){ for(int i=0;i<n;i++) if(strcmp(s[i].nombre,nom)==0) return &s[i]; return NULL; }

unsigned long ultima=0;
String cmdBuf="";

void setup(){
  Serial.begin(9600); dht.begin();
  pinMode(LED_DIA, OUTPUT); pinMode(LED_TARDE, OUTPUT); pinMode(LED_NOCHE, OUTPUT);
  pinMode(RELAY_RIEGO, OUTPUT);
  pinMode(SPEAKER_PIN, OUTPUT); digitalWrite(SPEAKER_PIN, LOW);
  init_sensores(sensores);
  Serial.println("ESTACION_METEO_CSV");
}
void loop(){
  while(Serial.available()){
    char c=Serial.read();
    if(c=='\n' || c=='\r'){ cmdBuf.trim(); if(cmdBuf.length()){ 
      if(cmdBuf=="LED_ON") digitalWrite(LED_DIA,HIGH);
      else if(cmdBuf=="LED_OFF") digitalWrite(LED_DIA,LOW);
      else if(cmdBuf=="RELAY_ON") digitalWrite(RELAY_RIEGO,HIGH);
      else if(cmdBuf=="RELAY_OFF") digitalWrite(RELAY_RIEGO,LOW);
      Serial.print("COMANDO OK: "); Serial.println(cmdBuf);
      cmdBuf="";
    }} else cmdBuf+=c;
  }
  if(millis()-ultima >= INTERVALO_MS){
    leer_todos(sensores,6);
    alertar_todos(sensores,6);
    // Speaker si llueve
    Sensor *agua = buscar_sensor(sensores,6,"LLUVIA");
    if (agua && agua->valor > 500) digitalWrite(SPEAKER_PIN, HIGH);
    else digitalWrite(SPEAKER_PIN, LOW);

    Sensor *t=buscar_sensor(sensores,6,"DHT11_TEMP");
    Sensor *h=buscar_sensor(sensores,6,"DHT11_HUM");
    Sensor *ldr=buscar_sensor(sensores,6,"LDR");
    if(t && h){
      Serial.print(t->valor,1); Serial.print(","); Serial.print(h->valor,0);
      Serial.print(","); Serial.print(ldr?ldr->valor:0,0);
      Serial.print(","); Serial.println(agua?agua->valor:0,0);
    }
    ultima=millis();
  }
}

const int NUM_PULSANTI = 12;

const int pinPulsanti[NUM_PULSANTI] = {
  A5,   // tasto 1
  2,    // tasto 2
  3,
  4,
  5,
  6,
  7,
  8,
  9,
  10,
  11,   // tasto 11
  A0    // tasto 12
};

bool statoPrecedente[NUM_PULSANTI];

void setup() {
  Serial.begin(9600);

  for (int i = 0; i < NUM_PULSANTI; i++) {
    pinMode(pinPulsanti[i], INPUT_PULLUP);
    statoPrecedente[i] = digitalRead(pinPulsanti[i]);
  }

  Serial.println("PRONTO");
}

void loop() {
  for (int i = 0; i < NUM_PULSANTI; i++) {
    bool statoAttuale = digitalRead(pinPulsanti[i]);

    if (statoPrecedente[i] == HIGH && statoAttuale == LOW) {
      Serial.println("beep");
      Serial.print("PULSANTE:");
      Serial.println(i + 1);
      delay(250);
    }

    statoPrecedente[i] = statoAttuale;
  }
}
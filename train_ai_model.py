"""
Treniranje AI modela za detekciju anomalija na pumpi (ELKON demo)

Isolation Forest - uci normalan obrazac rada (vibracija + struja) iz
istorijskih podataka, bez potrebe za labelovanim primjerima kvara.
Anomalije se izoluju sa manje slucajnih podjela stabla nego normalne
tacke - otud "anomaly score" = prosjecan broj podjela do izolacije.

is_simulated_fault kolona se koristi SAMO za evaluaciju na kraju, ne za
trening - model je "slijep" za nju, kao sto bi bio i na pravim podacima.

Izlaz: isolation_forest_model.joblib, feature_scaler.joblib
Zavisnosti: pandas, scikit-learn, joblib
"""

import argparse

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import confusion_matrix, precision_score, recall_score, accuracy_score


def ucitaj_podatke(putanja_csv: str) -> pd.DataFrame:
    df = pd.read_csv(putanja_csv)

    if df["is_simulated_fault"].dtype == object:
        df["is_simulated_fault"] = df["is_simulated_fault"].map({"True": True, "False": False})

    broj_kvarova = df["is_simulated_fault"].sum()
    print(f"[UCITAVANJE] {len(df)} redova, {broj_kvarova} "
          f"({100 * broj_kvarova / len(df):.2f}%) tokom simuliranog kvara")
    print(df[["vibration_mms", "current_a"]].describe().to_string())

    return df


def treniraj_model(df: pd.DataFrame, contamination):
    # Skaliranje jer vibracija (~0-20) i struja (~0-15) imaju razlicite opsege
    X = df[["vibration_mms", "current_a"]].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    print(f"\n[TRENING] Isolation Forest, contamination={contamination}")
    model = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)
    return model, scaler, X_scaled


def evaluiraj_model(df: pd.DataFrame, model, X_scaled):
    predikcija_anomalija = model.predict(X_scaled) == -1
    stvarna_anomalija = df["is_simulated_fault"].values

    tacnost = accuracy_score(stvarna_anomalija, predikcija_anomalija)
    preciznost = precision_score(stvarna_anomalija, predikcija_anomalija, zero_division=0)
    odziv = recall_score(stvarna_anomalija, predikcija_anomalija, zero_division=0)

    print(f"\nTacnost: {tacnost*100:.2f}%  Preciznost: {preciznost*100:.2f}%  "
          f"Odziv: {odziv*100:.2f}%")

    cm = confusion_matrix(stvarna_anomalija, predikcija_anomalija)
    print("Matrica konfuzije [normalno, anomalija]:")
    print(cm)
    print(f"Propusteni kvarovi (false negative): {cm[1][0]} - ovo je kljucna metrika "
          f"za odrzavanje, treba biti sto nize")


def sacuvaj_model(model, scaler, putanja_model: str, putanja_scaler: str):
    joblib.dump(model, putanja_model)
    joblib.dump(scaler, putanja_scaler)
    print(f"\n[SACUVANO] {putanja_model}, {putanja_scaler}")


def main():
    parser = argparse.ArgumentParser(description="Trening AI modela - detekcija anomalija pumpe")
    parser.add_argument("--input", default="pumpa_istorijski_podaci.csv")
    parser.add_argument("--model-out", default="isolation_forest_model.joblib")
    parser.add_argument("--scaler-out", default="feature_scaler.joblib")
    parser.add_argument("--contamination", default="auto",
                         help="Ocekivani % anomalija (npr. 0.02) ili 'auto'")
    args = parser.parse_args()

    contamination = args.contamination if args.contamination == "auto" else float(args.contamination)

    df = ucitaj_podatke(args.input)
    model, scaler, X_scaled = treniraj_model(df, contamination)
    evaluiraj_model(df, model, X_scaled)
    sacuvaj_model(model, scaler, args.model_out, args.scaler_out)


if __name__ == "__main__":
    main()

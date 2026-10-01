using System;

// Banco Ficticio S.A.: aplicación de ejemplo, datos inventados.
public static class ComisionService
{
    // Hasta 1.000 USD la comisión es fija; desde ahí es el 0,1 % del monto, con un tope de 5,00.
    // La transferencia inmediata suma 1,00.
    public static decimal Calcular(decimal monto, string tipo)
    {
        decimal comision = monto <= 1000m ? 0.50m : Math.Round(monto * 0.001m, 2, MidpointRounding.AwayFromZero);
        if (comision > 5.00m)
        {
            comision = 5.00m;
        }
        if (tipo == "INM")
        {
            comision += 1.00m;
        }
        return comision;
    }
}

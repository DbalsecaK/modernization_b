using System;
using System.Configuration;
using System.Data.SqlClient;
using System.Web.UI;

// Banco Ficticio S.A.: aplicación de ejemplo, datos inventados.
public partial class Comprobante : Page
{
    protected void Page_Load(object sender, EventArgs e)
    {
        int numero = int.Parse(Request.QueryString["numero"]);
        string conexion = ConfigurationManager.ConnectionStrings["Banco"].ConnectionString;
        using (SqlConnection cn = new SqlConnection(conexion))
        {
            cn.Open();
            SqlCommand leer = new SqlCommand(
                "SELECT TRF_MONTO FROM TRANSFERENCIAS WHERE TRF_NUMERO = @numero", cn);
            leer.Parameters.AddWithValue("@numero", numero);
            object monto = leer.ExecuteScalar();
            lblNumero.Text = numero.ToString();
            lblMonto.Text = monto == null ? string.Empty : ((decimal)monto).ToString("0.00");
        }
    }
}

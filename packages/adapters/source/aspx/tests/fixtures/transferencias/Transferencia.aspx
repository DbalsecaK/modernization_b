<%@ Page Language="C#" AutoEventWireup="true" CodeFile="Transferencia.aspx.cs" Inherits="Transferencia" %>
<%-- Banco Ficticio S.A.: aplicación de ejemplo, datos inventados. --%>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head runat="server">
    <title>Transferencia entre cuentas</title>
</head>
<body>
    <form id="form1" runat="server">
        <h1>Transferencia entre cuentas</h1>
        <asp:Label ID="lblOrigen" runat="server" AssociatedControlID="txtCuentaOrigen" Text="Cuenta origen" />
        <asp:TextBox ID="txtCuentaOrigen" runat="server" MaxLength="10" />
        <asp:RequiredFieldValidator ID="rfvOrigen" runat="server" ControlToValidate="txtCuentaOrigen"
            ErrorMessage="Ingrese la cuenta origen" />
        <asp:RegularExpressionValidator ID="revOrigen" runat="server" ControlToValidate="txtCuentaOrigen"
            ValidationExpression="^\d{10}$" ErrorMessage="La cuenta tiene 10 dígitos" />

        <asp:Label ID="lblDestino" runat="server" AssociatedControlID="txtCuentaDestino" Text="Cuenta destino" />
        <asp:TextBox ID="txtCuentaDestino" runat="server" MaxLength="10" />
        <asp:RequiredFieldValidator ID="rfvDestino" runat="server" ControlToValidate="txtCuentaDestino"
            ErrorMessage="Ingrese la cuenta destino" />

        <asp:Label ID="lblMontoTexto" runat="server" AssociatedControlID="txtMonto" Text="Monto (USD)" />
        <asp:TextBox ID="txtMonto" runat="server" MaxLength="9" />
        <asp:RequiredFieldValidator ID="rfvMonto" runat="server" ControlToValidate="txtMonto"
            ErrorMessage="Ingrese el monto" />
        <asp:RangeValidator ID="rvMonto" runat="server" ControlToValidate="txtMonto" Type="Currency"
            MinimumValue="1" MaximumValue="10000" ErrorMessage="El monto va de 1 a 10.000" />

        <asp:Label ID="lblTipoTexto" runat="server" AssociatedControlID="ddlTipo" Text="Tipo" />
        <asp:DropDownList ID="ddlTipo" runat="server">
            <asp:ListItem Value="PRO" Text="Programada" />
            <asp:ListItem Value="INM" Text="Inmediata" />
        </asp:DropDownList>

        <asp:Button ID="btnTransferir" runat="server" Text="Transferir" OnClick="btnTransferir_Click" />
        <asp:Button ID="btnCancelar" runat="server" Text="Cancelar" CausesValidation="false"
            PostBackUrl="~/Inicio.aspx" />

        <asp:Label ID="lblComision" runat="server" />
        <asp:Label ID="lblMensaje" runat="server" />
    </form>
</body>
</html>
